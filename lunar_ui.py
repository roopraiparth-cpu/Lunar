"""Native desktop shell for Lunar.

Replaces the browser UI with a plain Tkinter window: no embedded browser, no
CDN fonts, no canvas/WebGL. That keeps the whole app inside one GDI-rendered
process, so it costs a fraction of the RAM and none of the GPU compositing a
browser tab needed.

Design rules for this file, in order of importance:
  * Idle means idle. Widgets update only when a value actually changed, the arc
    core only redraws while Lunar is listening, working, or speaking, and the
    poll slows to one cheap state read per second when nothing is happening.
  * No cross-thread Tk calls. Worker threads publish plain values that the UI
    thread picks up on its next tick.
  * Everything optional (speech, settings file) degrades quietly if missing.
"""

import json
import os
import queue
import threading
import time
import webbrowser
from pathlib import Path

import tkinter as tk


CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "Lunar"
CONFIG_PATH = CONFIG_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "voice": "",      # SAPI voice description; empty means the system default
    "rate": 0.95,     # speech speed multiplier
    "speak": True,    # speak responses out loud
    "dark": True,     # appearance
}

SAPI_ASYNC = 1
SAPI_PURGE = 2


def _dark_palette():
    return {
        "bg": "#0c1216",
        "panel": "#121b21",
        "panel_alt": "#16212a",
        "line": "#22303a",
        "track": "#1b262e",
        "ink": "#e8eef4",
        "muted": "#8a99a8",
        "faint": "#5c6b78",
        "accent": "#86b7d8",
        "violet": "#9a90c4",
        "amber": "#d9a05a",
        "ok": "#8cb79a",
        "bad": "#c58487",
        "button": "#16212a",
        "button_hover": "#1e2c36",
        "button_active": "#24384a",
        "button_ink": "#cfe0ec",
        "entry": "#0f171c",
        "core_ring": "#1d2c36",
    }


def _light_palette():
    return {
        "bg": "#eef2f5",
        "panel": "#ffffff",
        "panel_alt": "#f4f7f9",
        "line": "#d3dde4",
        "track": "#dde5ea",
        "ink": "#1c2730",
        "muted": "#5b6b78",
        "faint": "#8494a1",
        "accent": "#2b6f8f",
        "violet": "#5c5490",
        "amber": "#9a6b22",
        "ok": "#3f7d5c",
        "bad": "#8c3f43",
        "button": "#f4f7f9",
        "button_hover": "#e6edf2",
        "button_active": "#d5e4ee",
        "button_ink": "#1c2730",
        "entry": "#ffffff",
        "core_ring": "#cddae2",
    }


def _load_settings():
    """Read persisted settings, falling back to defaults for anything missing."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            for key in DEFAULT_SETTINGS:
                if key in stored:
                    settings[key] = stored[key]
    except (OSError, ValueError):
        pass
    try:
        settings["rate"] = max(0.5, min(1.5, float(settings["rate"])))
    except (TypeError, ValueError):
        settings["rate"] = DEFAULT_SETTINGS["rate"]
    settings["speak"] = bool(settings["speak"])
    settings["dark"] = bool(settings["dark"])
    return settings


def _save_settings(settings):
    """Persist settings; a failed write must never interrupt the assistant."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        pass


def _dark_titlebar(window):
    """Ask DWM for a dark title bar so the chrome matches the JARVIS panel."""
    try:
        import ctypes

        handle = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # 20 = Win10 2004+/Win11, 19 = older builds
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(handle), ctypes.c_int(attribute), ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if result == 0:
                break
    except Exception:
        pass


def _enable_dpi_awareness():
    """Keep text crisp on scaled displays instead of letting Windows stretch it."""
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class Speaker:
    """Windows SAPI speech, replacing the browser's speechSynthesis.

    One worker thread owns the COM voice object. Utterances run on that thread so
    speech is serialised naturally, and ``interrupt`` purges the engine from the
    caller's thread, so a new reply cuts off the old one mid-sentence.
    """

    def __init__(self, settings):
        self._settings = settings
        self._queue = queue.Queue()
        self._stop = object()
        self._voice = None
        self._voice_lock = threading.Lock()
        self._thread = None
        self._engaged = False          # true from speak() until the audio ends
        self._voices = []              # descriptions, published by the worker
        self._pending_voices = False
        self._available = False
        self._muted = not settings.get("speak", True)

    @property
    def busy(self):
        """True while audio is playing; drives the core animation."""
        return self._engaged

    @property
    def available(self):
        """False when pywin32 is missing or SAPI could not be created."""
        return self._available

    def take_voices(self):
        """Hand the freshly enumerated voice list to the UI, once."""
        if not self._pending_voices:
            return None
        self._pending_voices = False
        return list(self._voices)

    def speak(self, text):
        """Queue an utterance, dropping anything still waiting to be spoken."""
        if self._muted:
            return
        text = (text or "").strip()
        if not text or not self._available:
            return
        self.interrupt()
        self._queue.put(text)

    def interrupt(self):
        """Stop current audio immediately and clear anything still queued."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with self._voice_lock:
            voice = self._voice
        if voice is not None:
            try:
                voice.Speak("", SAPI_ASYNC | SAPI_PURGE)
            except Exception:
                pass
        self._engaged = False

    def set_muted(self, muted):
        self._muted = bool(muted)
        if self._muted:
            self.interrupt()

    def set_voice(self, description):
        self._settings["voice"] = description or ""

    def shutdown(self):
        self.interrupt()
        self._queue.put(self._stop)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _apply_voice(self):
        """Select the configured voice, falling back to the engine default."""
        voice = self._voice
        wanted = (self._settings.get("voice") or "").strip().lower()
        if voice is None or not wanted:
            return
        try:
            tokens = voice.GetVoices()
            for index in range(tokens.Count):
                token = tokens.Item(index)
                if (token.GetDescription() or "").strip().lower() == wanted:
                    voice.Voice = token
                    return
        except Exception:
            pass

    def _run(self):
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            return
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass

        try:
            voice = win32com.client.Dispatch("SAPI.SpVoice")
        except Exception:
            self._finish_com(pythoncom)
            return

        with self._voice_lock:
            self._voice = voice
        self._available = True

        try:
            tokens = voice.GetVoices()
            self._voices = sorted(
                (tokens.Item(index).GetDescription() or "").strip()
                for index in range(tokens.Count)
            )
        except Exception:
            self._voices = []
        self._pending_voices = True

        self._apply_voice()

        while True:
            item = self._queue.get()
            if item is self._stop:
                break
            try:
                self._speak(item)
            except Exception:
                self._engaged = False
        self._engaged = False

        self.interrupt()
        with self._voice_lock:
            self._voice = None
        self._finish_com(pythoncom)

    @staticmethod
    def _finish_com(pythoncom):
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass

    def _speak(self, text):
        """Speak one utterance, keeping the engaged flag honest for the UI."""
        voice = self._voice
        if voice is None:
            return
        try:
            rate = float(self._settings.get("rate", 0.95))
            voice.Rate = max(-10, min(10, int(round((rate - 1.0) * 8))))
            voice.Volume = 100
        except Exception:
            pass
        self._apply_voice()
        self._engaged = True
        try:
            voice.Speak(text, 0)  # blocking: keeps the flag true for the duration
        except Exception:
            pass
        finally:
            self._engaged = False


class LunarApp:
    """The Lunar desktop window."""

    POLL_IDLE = 1000     # ms between state reads while nothing is happening
    POLL_BUSY = 100      # ms while the core is animating

    def __init__(self, app):
        self.app = app                 # the main module: CONTROLLER, metrics, controls
        self.settings = _load_settings()
        self.colors = _dark_palette() if self.settings["dark"] else _light_palette()

        self.root = tk.Tk()
        self.root.title("Lunar")
        self.root.configure(bg=self.colors["bg"])
        self.root.minsize(430, 720)
        self.root.geometry("470x790")
        _dark_titlebar(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.speaker = Speaker(self.settings)
        self.vars = {
            "rate": tk.DoubleVar(value=self.settings["rate"]),
            "speak": tk.BooleanVar(value=self.settings["speak"]),
            "dark": tk.BooleanVar(value=self.settings["dark"]),
        }

        # Widget registries, so re-theming is a loop instead of a tree walk.
        self._frames = []
        self._labels = []
        self._buttons = []
        self._menus = []
        self._rows = {}

        self._last_revision = None
        self._last_state = {}
        self._core_signature = None
        self._shown = {}               # rendered values, to skip untouched widgets
        self._poll_scheduled = False
        self._poll_handle = None
        self._next_delay = 0
        self._closing = False

        self._build()

    # ---------------- registry helpers ----------------
    def _frame(self, master, role="bg", **options):
        frame = tk.Frame(master, bg=self.colors[role], **options)
        self._frames.append((frame, role))
        return frame

    def _label(self, master, fg, text="", bg="bg", **options):
        options.setdefault("font", ("Segoe UI", 9))
        label = tk.Label(master, text=text, bg=self.colors[bg], fg=self.colors[fg], **options)
        self._labels.append((label, fg, bg))
        return label

    def _button(self, master, text, command, kind="quiet", **options):
        button = tk.Button(master, text=text, command=command, **options)
        self._buttons.append((button, kind))
        return button

    def _menubutton(self, master, text, **options):
        button = tk.Menubutton(master, text=text, **options)
        self._buttons.append((button, "quiet"))
        return button

    def _menu(self, master):
        menu = tk.Menu(
            master, tearoff=0, bg=self.colors["panel_alt"], fg=self.colors["ink"],
            activebackground=self.colors["button_active"], activeforeground=self.colors["ink"],
            font=("Segoe UI", 9),
        )
        self._menus.append(menu)
        return menu

    # ---------------- construction ----------------
    def _build(self):
        self._build_header()
        self._build_core()
        self._build_conversation()
        self._build_telemetry()
        self._build_actions()
        self._build_entry()
        self._build_settings()
        self._build_footer()
        self.speaker.start()

    def _build_header(self):
        header = self._frame(self.root)
        header.pack(fill="x", padx=18, pady=(16, 4))

        self._label(header, "ink", "L U N A R", font=("Segoe UI", 13, "bold")).pack(side="left")

        self.status_pill = self._label(
            header, "ok", "READY", font=("Segoe UI", 8, "bold"), padx=10, pady=4,
        )
        self.status_pill.configure(bg=self.colors["panel_alt"])
        self.status_pill.pack(side="right")

        self.call_banner = self._frame(self.root, "panel_alt")
        self._label(self.call_banner, "amber", "INCOMING CALL", bg="panel_alt",
                    font=("Segoe UI", 8, "bold")).pack(side="left", padx=10, pady=6)
        self.call_name = self._label(self.call_banner, "ink", "", bg="panel_alt",
                                     font=("Segoe UI", 9))
        self.call_name.pack(side="left", padx=2)

    def _build_core(self):
        holder = self._frame(self.root)
        self.core_holder = holder
        holder.pack(pady=(2, 0))
        self.core = tk.Canvas(
            holder, width=196, height=196, bg=self.colors["bg"],
            highlightthickness=0, bd=0,
        )
        self._frames.append((self.core, "bg"))
        self.core.pack()
        self._core_angle = 0.0
        self._draw_core(time.monotonic(), force=True)

    def _build_conversation(self):
        box = self._frame(self.root)
        box.pack(fill="x", padx=18, pady=(8, 2))

        self.message = self._label(
            box, "ink", "Ready for a command", font=("Segoe UI", 11),
            wraplength=420, justify="center", height=2,
        )
        self.message.pack(fill="x")

        self.heard = self._label(
            box, "faint", "", font=("Segoe UI", 9), wraplength=420, justify="center",
        )
        self.heard.pack(fill="x")

    def _build_telemetry(self):
        self.telemetry = self._frame(self.root, "panel")
        self.telemetry.pack(fill="x", padx=18, pady=(10, 2))

        for key, label in (
            ("cpu", "CPU"), ("ram", "RAM"), ("gpu", "GPU"), ("battery", "BATTERY"),
        ):
            self._rows[key] = self._add_row(label, stepper=None)
        self._rows["volume"] = self._add_row("VOLUME", stepper="volume")
        self._rows["brightness"] = self._add_row("SCREEN", stepper="brightness")

    def _add_row(self, caption, stepper):
        """One telemetry line: caption, bar, value, optional stepper buttons."""
        row = self._frame(self.telemetry, "panel")
        row.pack(fill="x", padx=14, pady=5)

        self._label(row, "muted", caption, bg="panel", font=("Segoe UI", 8), width=7,
                    anchor="w").pack(side="left")

        track = tk.Frame(row, bg=self.colors["track"], height=7)
        track.pack(side="left", fill="x", expand=True, padx=(4, 10))
        track.pack_propagate(False)
        fill = tk.Frame(track, bg=self.colors["accent"])
        fill.place(x=0, y=0, relwidth=0.0, relheight=1)

        value = self._label(row, "ink", "--", bg="panel", font=("Segoe UI", 9),
                           width=9, anchor="e")
        value.pack(side="left")

        if stepper:
            for symbol, action in (("-", "down"), ("+", "up")):
                button = self._button(
                    row, symbol, command=lambda a=action, k=stepper: self._step(k, a),
                    kind="step", width=2, font=("Segoe UI", 8), padx=0, pady=1,
                    relief="flat", bd=0, highlightthickness=1,
                )
                button.pack(side="left", padx=(6, 0))

        return {"track": track, "fill": fill, "value": value}

    def _build_actions(self):
        row = self._frame(self.root)
        row.pack(fill="x", padx=18, pady=(10, 4))

        self.listen_button = self._button(
            row, "Listen", self._toggle_listen, kind="action",
            font=("Segoe UI", 11, "bold"), padx=8, pady=8, relief="flat", bd=0,
            highlightthickness=1,
        )
        self.listen_button.pack(side="left", fill="x", expand=True)

        self.wake_button = self._button(
            row, "Hands-free", self._toggle_wake, kind="action",
            font=("Segoe UI", 9), width=12, padx=6, pady=6, relief="flat", bd=0,
            highlightthickness=1,
        )
        self.wake_button.pack(side="left", padx=(8, 0))

        self.sound_button = self._button(
            row, "Sound", self._toggle_sound, kind="action",
            font=("Segoe UI", 9), width=7, padx=6, pady=6, relief="flat", bd=0,
            highlightthickness=1,
        )
        self.sound_button.pack(side="left", padx=(8, 0))

        quick = self._frame(self.root)
        quick.pack(fill="x", padx=18, pady=(0, 2))
        for text, command in (
            ("Volume up", lambda: self._run("volume up")),
            ("Volume down", lambda: self._run("volume down")),
            ("Brighter", lambda: self._run("brightness up")),
            ("Dimmer", lambda: self._run("brightness down")),
            ("Exit", self.quit),
        ):
            self._button(
                quick, text, command, kind="quiet", font=("Segoe UI", 9), padx=6, pady=6,
                relief="flat", bd=0, highlightthickness=1,
            ).pack(side="left", padx=(0, 6))

    def _build_entry(self):
        row = self._frame(self.root)
        row.pack(fill="x", padx=18, pady=(6, 4))

        self.entry = tk.Entry(
            row, bg=self.colors["entry"], fg=self.colors["ink"],
            insertbackground=self.colors["ink"], relief="flat", bd=0,
            highlightthickness=1, highlightbackground=self.colors["line"],
            highlightcolor=self.colors["accent"], font=("Segoe UI", 10),
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=8, ipadx=8)
        self.entry.bind("<Return>", lambda _event: self._submit())
        self.entry.bind("<KP_Enter>", lambda _event: self._submit())

        self._button(
            row, "Send", self._submit, kind="quiet", font=("Segoe UI", 9), width=6,
            padx=6, pady=6, relief="flat", bd=0, highlightthickness=1,
        ).pack(side="left", padx=(8, 0))

    def _build_settings(self):
        self.settings_panel = self._frame(self.root, "panel")

        voice_row = self._frame(self.settings_panel, "panel")
        voice_row.pack(fill="x", padx=14, pady=(10, 2))
        self._label(voice_row, "muted", "Voice", bg="panel", font=("Segoe UI", 8)).pack(side="left")

        self.voice_menu = self._menubutton(
            voice_row, "System default",
            font=("Segoe UI", 9), width=22, anchor="w", indicatoron=True,
            relief="flat", bd=0, highlightthickness=1,
        )
        self.voice_dropdown = self._menu(self.voice_menu)
        self.voice_menu.configure(menu=self.voice_dropdown)
        # Tk rejects -postcommand once -menu is set, and an instance binding runs
        # before the class binding that drops the menu down, so populate here.
        self.voice_menu.bind("<Button-1>", lambda _event: self._refresh_voices())
        self.voice_menu.pack(side="left", fill="x", expand=True, padx=(8, 0))

        rate_row = self._frame(self.settings_panel, "panel")
        rate_row.pack(fill="x", padx=14, pady=4)
        self._label(rate_row, "muted", "Speed", bg="panel", font=("Segoe UI", 8),
                    width=7, anchor="w").pack(side="left")

        self.rate = tk.Scale(
            rate_row, from_=0.5, to=1.5, resolution=0.05, orient="horizontal",
            variable=self.vars["rate"], command=self._on_rate, showvalue=True, length=200,
            bg=self.colors["panel"], fg=self.colors["ink"], troughcolor=self.colors["track"],
            highlightthickness=0, bd=0, sliderrelief="flat",
            activebackground=self.colors["accent"], font=("Segoe UI", 8),
        )
        self._scales = [self.rate]
        self.rate.pack(side="left", fill="x", expand=True, padx=4)

        self.speak_toggle = self._checkbutton(
            self.settings_panel, "Speak responses", self.vars["speak"], self._on_speak_toggle
        )
        self.speak_toggle.pack(fill="x", padx=14, pady=2)

        self.theme_toggle = self._checkbutton(
            self.settings_panel, "Dark appearance", self.vars["dark"], self._on_theme_toggle
        )
        self.theme_toggle.pack(fill="x", padx=14, pady=(0, 10))

    def _checkbutton(self, master, text, variable, command):
        return tk.Checkbutton(
            master, text=text, variable=variable, command=command,
            bg=self.colors["panel"], fg=self.colors["ink"],
            selectcolor=self.colors["panel_alt"], activebackground=self.colors["panel"],
            activeforeground=self.colors["ink"], highlightthickness=0, bd=0,
            font=("Segoe UI", 9), anchor="w",
        )

    def _build_footer(self):
        self.footer = self._frame(self.root)
        self.footer.pack(side="bottom", fill="x", padx=18, pady=(4, 14))

        self.footer_hint = self._label(self.footer, "faint", "", font=("Segoe UI", 8), anchor="w")
        self.footer_hint.pack(side="left")

        self.settings_button = self._label(self.footer, "muted", "Settings",
                                           font=("Segoe UI", 8), cursor="hand2")
        self.settings_button.pack(side="right")
        self.settings_button.bind("<Button-1>", self._toggle_settings)

    # ---------------- theming ----------------
    def _apply_theme(self):
        """Repaint every registered widget with the current palette."""
        colors = self.colors

        for widget, role in self._frames:
            widget.configure(bg=colors[role])
        for widget, fg, bg in self._labels:
            widget.configure(bg=colors[bg], fg=colors[fg])
        for widget, kind in self._buttons:
            if kind == "action":
                widget.configure(
                    bg=colors["button_active"], fg=colors["ink"],
                    activebackground=colors["accent"], activeforeground=colors["bg"],
                    highlightbackground=colors["line"],
                )
            else:
                widget.configure(
                    bg=colors["button"], fg=colors["button_ink"],
                    activebackground=colors["button_hover"], activeforeground=colors["ink"],
                    highlightbackground=colors["line"],
                )
        for row in self._rows.values():
            row["track"].configure(bg=colors["track"])
            row["fill"].configure(bg=colors["accent"])
            row["value"].configure(bg=colors["panel"], fg=colors["ink"])
        for menu in self._menus:
            menu.configure(
                bg=colors["panel_alt"], fg=colors["ink"],
                activebackground=colors["button_active"], activeforeground=colors["ink"],
            )

        for scale in self._scales:
            scale.configure(
                bg=colors["panel"], fg=colors["ink"], troughcolor=colors["track"],
                activebackground=colors["accent"],
            )
        for check in (self.speak_toggle, self.theme_toggle):
            check.configure(
                bg=colors["panel"], fg=colors["ink"], selectcolor=colors["panel_alt"],
                activebackground=colors["panel"], activeforeground=colors["ink"],
            )

        self.entry.configure(
            bg=colors["entry"], fg=colors["ink"], insertbackground=colors["ink"],
            highlightbackground=colors["line"], highlightcolor=colors["accent"],
        )
        self.status_pill.configure(bg=colors["panel_alt"])

        self._shown.clear()   # cached text no longer reflects what is on screen
        self._core_signature = None

    def _on_theme_toggle(self):
        self.settings["dark"] = bool(self.vars["dark"].get())
        self.colors = _dark_palette() if self.settings["dark"] else _light_palette()
        _save_settings(self.settings)
        self._apply_theme()

    # ---------------- settings panel ----------------
    def _toggle_settings(self, _event=None):
        # winfo_manager reports the geometry manager regardless of whether the
        # window is currently mapped, so a minimised window stays correct.
        if self.settings_panel.winfo_manager():
            self.settings_panel.pack_forget()
        else:
            self.settings_panel.pack(fill="x", padx=18, pady=(4, 0), before=self.footer)
        # Grow or shrink to whatever the content needs, keeping the user's width.
        self.root.update_idletasks()
        self.root.geometry(f"{self.root.winfo_width()}x{self.root.winfo_reqheight()}")

    def _refresh_voices(self):
        """Fill the voice dropdown from whatever SAPI has installed."""
        menu = self.voice_dropdown
        menu.delete(0, "end")
        menu.add_command(label="System default", command=lambda: self._choose_voice(""))
        voices = self.speaker.take_voices()
        if voices is None:
            return          # worker is still enumerating; repopulate next open
        for description in voices:
            menu.add_command(
                label=description,
                command=lambda value=description: self._choose_voice(value),
            )

    def _choose_voice(self, description):
        self.speaker.set_voice(description)
        self.voice_menu.configure(text=description or "System default")
        _save_settings(self.settings)
        self.speaker.speak("Voice set.")

    def _on_rate(self, value):
        try:
            self.settings["rate"] = round(float(value), 2)
        except (TypeError, ValueError):
            return
        _save_settings(self.settings)

    def _on_speak_toggle(self):
        enabled = bool(self.vars["speak"].get())
        self.settings["speak"] = enabled
        self.speaker.set_muted(not enabled)
        _save_settings(self.settings)

    def _toggle_sound(self):
        self.speak_toggle.invoke()
        if self.settings["speak"]:
            self.speaker.speak("Voice responses on.")
        self._request_poll(self.POLL_BUSY)

    # ---------------- commands ----------------
    def _toggle_listen(self):
        self.app.CONTROLLER.start_listening()
        self._request_poll(self.POLL_BUSY)

    def _toggle_wake(self):
        state = self.app.CONTROLLER.get_state()
        if state.get("wake_enabled") or state.get("wake_stopping"):
            self.app.CONTROLLER.stop_wake_mode()
        else:
            self.app.CONTROLLER.start_wake_mode()
        self._request_poll(self.POLL_BUSY)

    def _run(self, text):
        """Send a phrase through the same path a spoken command takes."""
        self.app.CONTROLLER.run_text_command(text)
        self._request_poll(self.POLL_BUSY)

    def _submit(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        started, _state = self.app.CONTROLLER.run_text_command(text)
        if not started:
            self._set("message", self.message,
                      "Turn off hands-free mode before typing commands.")
        self._request_poll(self.POLL_BUSY)

    def _step(self, kind, direction):
        """Nudge volume or brightness straight from a telemetry row."""
        delta = 10 if direction == "up" else -10
        if kind == "volume":
            current = self.app.get_system_volume()
            self.app.set_system_volume((50 if current is None else current) + delta)
        else:
            current = self.app.get_screen_brightness()
            self.app.set_screen_brightness((50 if current is None else current) + delta)
        self._request_poll(self.POLL_BUSY)

    # ---------------- core drawing ----------------
    def _core_look(self):
        """Colour and spin speed for the current activity."""
        state = self._last_state
        status = state.get("status", "ready")
        wake = bool(state.get("wake_enabled"))
        dictating = bool(state.get("dictation_enabled")) and wake

        if status == "processing":
            return self.colors["amber"], 220.0
        if self.speaker.busy:
            return self.colors["violet"], 90.0
        if status == "listening":
            return self.colors["ok"], 45.0
        if dictating:
            return self.colors["violet"], 60.0
        if wake:
            return self.colors["accent"], 22.0
        return self.colors["faint"], 0.0

    def _draw_core(self, now, force=False):
        """Paint the arc reactor. Only runs while something is actually happening."""
        status = self._last_state.get("status", "ready")
        wake = bool(self._last_state.get("wake_enabled"))
        dictating = bool(self._last_state.get("dictation_enabled")) and wake
        speaking = self.speaker.busy
        color, speed = self._core_look()

        # Idle core is a still image: skip the repaint entirely until something
        # changes, which is what keeps an untouched window at ~0% CPU.
        signature = (status, wake, dictating, speaking, color)
        if not force and signature == self._core_signature and speed == 0:
            return
        self._core_signature = signature

        canvas = self.core
        colors = self.colors
        canvas.delete("all")
        center, radius = 98, 84

        canvas.create_oval(
            center - radius, center - radius, center + radius, center + radius,
            outline=colors["core_ring"], width=1,
        )

        self._core_angle = (self._core_angle + speed * 0.05) % 360
        start = self._core_angle

        # A pulsing ring says "I'm working" without a single word of text.
        intensity = 1.0
        if status in ("listening", "processing") or speaking or dictating:
            intensity = 1.0 + 0.06 * (0.5 + 0.5 * ((now * 1.6) % 1.0))

        canvas.create_arc(
            center - radius * intensity, center - radius * intensity,
            center + radius * intensity, center + radius * intensity,
            start=start, extent=110, style="arc", outline=color, width=3,
        )
        canvas.create_arc(
            center - radius, center - radius, center + radius, center + radius,
            start=(start + 180) % 360, extent=26, style="arc", outline=color, width=1,
        )

        inner = 46 if status == "processing" else 38
        canvas.create_oval(
            center - inner, center - inner, center + inner, center + inner,
            fill=colors["panel_alt"], outline=color, width=1,
        )

        if dictating and status == "ready":
            glyph = "DICTATE"
        elif status == "processing":
            glyph = "..."
        elif status == "listening":
            glyph = "LISTEN"
        elif status == "error":
            glyph = "MIC"
        elif wake and status == "ready":
            glyph = "SAY LUNAR"
        else:
            glyph = None
        if glyph:
            canvas.create_text(
                center, center, text=glyph, fill=colors["muted"],
                font=("Segoe UI", 7, "bold"),
            )

        if speaking:
            for index, spread in enumerate((1.14, 1.30)):
                pulse = (now * 0.7 + index * 0.5) % 1.0
                size = radius * (spread + 0.10 * pulse)
                canvas.create_oval(
                    center - size, center - size, center + size, center + size,
                    outline=color, width=1,
                )

    # ---------------- main loop ----------------
    def run(self):
        self._poll()
        self.root.mainloop()

    def _request_poll(self, delay):
        """Schedule the next tick, shortening the wait if one is already queued."""
        if self._closing:
            return
        if self._poll_scheduled:
            if delay >= self._next_delay:
                return
            self.root.after_cancel(self._poll_handle)
        self._poll_scheduled = True
        self._next_delay = delay
        self._poll_handle = self.root.after(delay, self._poll)

    def _poll(self):
        self._poll_scheduled = False
        if self._closing:
            return
        try:
            state = self.app.CONTROLLER.get_state()
            metrics = dict(self.app.SYSTEM_METRICS)
            metrics.update(self.app._CONTROLS_METRICS)
            self._handle_state(state, metrics)
        except tk.TclError:
            return                      # window is tearing down
        except Exception:
            pass
        self._request_poll(self.POLL_BUSY if self._animating() else self.POLL_IDLE)

    def _animating(self):
        state = self._last_state
        return bool(
            self.speaker.busy
            or state.get("status") in ("listening", "processing")
            or state.get("wake_enabled")
            or state.get("dictation_enabled")
            or state.get("incoming_call")
        )

    def _set(self, key, widget, value, **options):
        """Update a widget only when its value differs from what is on screen."""
        if self._shown.get(key) == value:
            return
        self._shown[key] = value
        widget.configure(text=value, **options)

    def _set_bar(self, key, row, percent):
        if self._shown.get(key) == percent:
            return
        self._shown[key] = percent
        row["fill"].place_configure(relwidth=max(0.0, min(1.0, percent / 100.0)))

    def _handle_state(self, state, metrics):
        self._last_state = state
        status = state.get("status", "ready")
        wake = bool(state.get("wake_enabled"))
        wake_stopping = bool(state.get("wake_stopping"))
        dictating = bool(state.get("dictation_enabled")) and wake
        busy = status in ("listening", "processing")

        self._set("message", self.message, state.get("message") or "Ready for a command")
        heard = state.get("heard") or ""
        self._set("heard", self.heard, f"Heard: {heard}" if heard else "")

        if status == "listening":
            label, pill, tone = "Listening...", "LISTENING", self.colors["ok"]
        elif status == "processing":
            label, pill, tone = "Working...", "WORKING", self.colors["amber"]
        elif status == "error":
            label, pill, tone = "Check microphone", "ERROR", self.colors["bad"]
        elif wake_stopping:
            label, pill, tone = "Stopping...", "STOPPING", self.colors["muted"]
        elif dictating:
            label, pill, tone = "Dictating", "DICTATING", self.colors["violet"]
        elif wake:
            label, pill, tone = "Say Lunar", "HANDS-FREE", self.colors["accent"]
        else:
            label, pill, tone = "Listen", "READY", self.colors["ok"]

        self._set("pill", self.status_pill, pill, fg=tone)
        self._set("wake_label", self.wake_button,
                  "Turning off..." if wake_stopping else ("Wake on" if wake else "Hands-free"))
        self._set("sound_label", self.sound_button,
                  "Sound" if self.settings["speak"] else "Muted")

        mic_ok = bool(state.get("microphone_available", True))
        self.listen_button.configure(text="No mic" if not mic_ok else label)
        self.listen_button.configure(
            state="disabled" if (busy or wake or wake_stopping or not mic_ok) else "normal"
        )
        self.wake_button.configure(
            state="disabled" if (wake_stopping or (busy and not wake) or not mic_ok) else "normal"
        )
        self.entry.configure(state="disabled" if (wake or wake_stopping) else "normal")

        self._update_call_banner(bool(state.get("incoming_call")), state.get("message"))
        self._update_telemetry(metrics)
        self._consume_result(state)
        self._draw_core(time.monotonic())

        self._set("footer", self.footer_hint,
                  "Say \"Lunar\" in hands-free mode" if self.settings["speak"] else "")

    def _update_call_banner(self, incoming, message):
        if not incoming:
            if self.call_banner.winfo_manager():
                self.call_banner.pack_forget()
            return
        name = message or "Incoming call"
        for prefix in ("Incoming call from ", "Incoming call "):
            if name.startswith(prefix):
                name = name[len(prefix):]
        self._set("call_name", self.call_name, name.rstrip("."))
        if not self.call_banner.winfo_manager():
            self.call_banner.pack(fill="x", padx=18, pady=(2, 6), before=self.core_holder)

    def _update_telemetry(self, metrics):
        rows = self._rows
        for key in ("cpu", "ram", "gpu"):
            value = metrics.get(key)
            self._set(key, rows[key]["value"], self._percent(value, "%"))
            self._set_bar(f"{key}_bar", rows[key], value or 0)

        battery = metrics.get("battery_percent")
        if battery is None:
            self._set("battery", rows["battery"]["value"],
                      "AC" if metrics.get("battery_charging") else "--")
            self._set_bar("battery_bar", rows["battery"], 0)
        else:
            charging = " *" if metrics.get("battery_charging") else ""
            self._set("battery", rows["battery"]["value"], f"{round(battery)}%{charging}")
            self._set_bar("battery_bar", rows["battery"], battery)

        volume = metrics.get("volume")
        self._set("volume", rows["volume"]["value"],
                  "muted" if metrics.get("volume_muted") else self._percent(volume, "%"))
        self._set_bar("volume_bar", rows["volume"], volume or 0)

        brightness = metrics.get("brightness")
        self._set("brightness", rows["brightness"]["value"], self._percent(brightness, "%"))
        self._set_bar("brightness_bar", rows["brightness"], brightness or 0)

    def _consume_result(self, state):
        """Act on a new revision: open any page, then speak the reply."""
        revision = int(state.get("revision") or 0)
        if self._last_revision is None:
            self._last_revision = revision
            return
        if revision == self._last_revision:
            return
        self._last_revision = revision

        url = state.get("open_url")
        if url:
            try:
                webbrowser.open(url, new=2)
            except Exception:
                pass
        self.speaker.speak(state.get("speech_text") or "")
        self._request_poll(self.POLL_BUSY)

    @staticmethod
    def _percent(value, suffix):
        return "--" if value is None else f"{round(value)}{suffix}"

    # ---------------- shutdown ----------------
    def quit(self):
        if self._closing:
            return
        self._closing = True
        try:
            self.speaker.shutdown()
            self.app.shutdown_app()
        finally:
            try:
                self.root.destroy()
            except Exception:
                pass


def run_desktop(app):
    """Create and run the Lunar desktop window against the main module."""
    _enable_dpi_awareness()
    LunarApp(app).run()


def notify_error(title, message, kind="error"):
    """Show a startup problem or refusal to start. The windowed build has no
    console, so this dialog is the only way the user finds out what happened."""
    try:
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        show = messagebox.showerror if kind == "error" else messagebox.showinfo
        show(title, message)
        root.destroy()
    except Exception:
        print(f"[{title}] {message}", flush=True)