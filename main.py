import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlsplit


# Windows: launch child processes without flashing a console window. Required for
# windowed (--noconsole) builds; evaluated to 0 on non-Windows platforms.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

HOST = "127.0.0.1"
PORT = 8765
PAGE_PATH = Path(__file__).with_name("lunar.html")

# The homework portal belongs to whichever school you attend, so it is
# configured rather than baked in. Point LUNAR_HOMEWORK_URL at your own portal:
#     set LUNAR_HOMEWORK_URL=https://your-school.example/feed
# Left unset, the "homework" command simply says it has no link to open.
HOMEWORK_ENV_VAR = "LUNAR_HOMEWORK_URL"
HOMEWORK_URL = os.environ.get(HOMEWORK_ENV_VAR, "").strip()

# The two interfaces: a native window (main.py) and the browser page (web.py).
# They share this server, this port, and everything below it - only the way you
# reach the assistant differs.
UI_DESKTOP = "desktop"
UI_WEB = "web"
SERVE_UI = False   # only the web build serves lunar.html

APP_ALIASES = {
    "browser": "microsoftedge",
    "calc": "calculator",
    "cloud": "claude",
    "chrome": "googlechrome",
    "email": "outlook",
    "filemanager": "fileexplorer",
    "files": "fileexplorer",
    "googlechrome": "googlechrome",
    "imageviewer": "photos",
    "mail": "outlook",
    "microsoft365": "microsoft365copilot",
    "microsoftedge": "microsoftedge",
    "microsoftexcel": "excel",
    "microsoftoutlook": "outlook",
    "microsoftpowerpoint": "powerpoint",
    "microsoftstore": "microsoftstore",
    "microsoftteams": "microsoftteams",
    "microsoftword": "word",
    "msword": "word",
    "mycomputer": "fileexplorer",
    "myfiles": "fileexplorer",
    "office": "microsoft365copilot",
    "powerpointpresentation": "powerpoint",
    "presentation": "powerpoint",
    "ppt": "powerpoint",
    "screenclip": "snippingtool",
    "snip": "snippingtool",
    "spreadsheet": "excel",
    "texteditor": "notepad",
    "thispc": "fileexplorer",
    "videoplayer": "mediaplayer",
    "voicerecorder": "soundrecorder",
    "webbrowser": "microsoftedge",
    "wordprocessor": "word",
}


try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import sounddevice as sd
except ImportError:
    sd = None


if sr is not None:
    class _MicrophoneStream:
        def __init__(self, sample_rate, chunk):
            self._stream = sd.RawInputStream(
                samplerate=sample_rate,
                blocksize=chunk,
                channels=1,
                dtype="int16",
            )
            self._running = False

        def start(self):
            if not self._running:
                self._stream.start()
                self._running = True

        def read(self, size):
            audio, _ = self._stream.read(size)
            return audio

        def stop(self):
            if self._running:
                self._stream.stop()
                self._running = False

        def close(self):
            self._stream.close()


    class SoundDeviceMicrophone(sr.AudioSource):
        SAMPLE_RATE = 16000
        SAMPLE_WIDTH = 2
        CHUNK = 1024

        def __init__(self):
            if sd is None:
                raise ImportError("sounddevice is not installed")
            self.stream = None

        def __enter__(self):
            self.stream = _MicrophoneStream(self.SAMPLE_RATE, self.CHUNK)
            self.stream.start()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
                self.stream = None

        def pause(self):
            if self.stream is not None:
                self.stream.stop()

        def resume(self):
            if self.stream is not None:
                self.stream.start()
else:
    SoundDeviceMicrophone = None


def normalize_app_name(name):
    return "".join(character for character in name.lower() if character.isalnum())


def find_wake_phrase(text):
    return re.search(r"^\s*lunar\b", text, flags=re.IGNORECASE)


def find_installed_app(requested_name):
    command = "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
        creationflags=CREATE_NO_WINDOW,
    )
    apps = json.loads(result.stdout)
    if isinstance(apps, dict):
        apps = [apps]

    search_name = normalize_app_name(requested_name)
    search_name = normalize_app_name(APP_ALIASES.get(search_name, search_name))

    exact_matches = [
        app for app in apps
        if normalize_app_name(app.get("Name", "")) == search_name
    ]
    if exact_matches:
        return exact_matches[0]

    partial_matches = [
        app for app in apps
        if search_name in normalize_app_name(app.get("Name", ""))
    ]
    if len(partial_matches) == 1:
        return partial_matches[0]
    if len(partial_matches) > 1:
        choices = ", ".join(app["Name"] for app in partial_matches[:5])
        raise LookupError(f"Several apps match: {choices}. Say the full app name.")

    return None


def open_application(requested_name):
    try:
        app = find_installed_app(requested_name)
        if app is None:
            return {"ok": False, "message": f"I couldn't find {requested_name} in the Windows app list."}

        app_id = app.get("AppID", "")
        if os.path.isfile(app_id):
            subprocess.Popen([app_id], creationflags=CREATE_NO_WINDOW)
        else:
            subprocess.Popen(
                ["explorer.exe", f"shell:AppsFolder\\{app_id}"],
                creationflags=CREATE_NO_WINDOW,
            )
        return {"ok": True, "message": f"Opening {app['Name']}.", "app": app["Name"]}
    except LookupError as error:
        return {"ok": False, "message": str(error)}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        return {"ok": False, "message": f"I couldn't open {requested_name}: {error}"}


# ---------------- Closing apps ----------------
# Never close these: the desktop shell, core Windows services, or Lunar itself.
PROTECTED_PROCESS_NAMES = {
    "explorer", "winlogon", "csrss", "services", "lsass", "smss", "wininit",
    "dwm", "sihost", "ctfmon", "svchost", "audiodg", "spoolsv", "searchhost",
    "shellexperiencehost", "startmenuexperiencehost", "textinputhost",
    "runtimebroker", "taskhostw", "wudfhost", "fontdrvhost", "memcompression",
    # Lunar's own server runs on python - closing it would shut the assistant down
    "python", "pythonw",
}

# Store apps run under process names that differ from their Start-menu name.
PROCESS_NAME_ALIASES = {
    "calculatorapp": "Calculator",
    "clockapp": "Clock",
    "paintapp": "Paint",
    "photosapp": "Photos",
    "cameraapp": "Camera",
    "immersivecontrolpanel": "Settings",
    "settingsapp": "Settings",
    "winstoreapp": "Microsoft Store",
    "bingmaps": "Maps",
    "yourphone": "Phone Link",
    "microsoftwindowsstore": "Microsoft Store",
    "snippingtool": "Snipping Tool",
    "photoviewer": "Photos",
    "mediaapp": "Media Player",
    "windowsmediaplayer": "Media Player",
}

CLOSE_PREFIXES = (
    "shut down ", "close ", "quit ", "exit ", "kill ", "terminate ", "stop ", "end ",
)
CLOSE_BARE_PHRASES = (
    "close", "quit", "exit", "kill", "terminate", "stop", "end", "shut down", "shut it",
)
CLOSE_CURRENT_PHRASES = (
    "close this app", "close the app", "close this program", "close this window",
    "close the window", "close current app", "close current window",
    "close the app i have open", "close the app im using", "close the app i am using",
    "close the app on my screen", "close this app for me", "close what im using",
    "close what i am using", "close what im looking at", "close what is open",
    "close the active window", "close the active app", "close the front window",
    "quit this app", "quit this window", "exit this app", "close it",
)
CLOSE_FILLER_WORDS = (
    "the ", "a ", "an ", "all ", "my ", "that ", "this ", "running ", "open ", "up ",
)
CLOSE_TRAILING_WORDS = (" for me", " please", " right now", " now", " already")


def _friendly_process_name(process_key):
    """Human label for a process key like 'msedge'."""
    return FRIENDLY_APP_NAMES.get(process_key) or PROCESS_NAME_ALIASES.get(process_key) or process_key.title()


def _close_name_candidates(requested_name):
    """Every spelling a spoken app name could match against a running process name."""
    base = normalize_app_name(requested_name)
    if not base:
        return set()
    candidates = {base}
    alias = normalize_app_name(APP_ALIASES.get(base, ""))
    if alias:
        candidates.add(alias)
    friendly = _friendly_process_name(base) or _friendly_process_name(alias or "")
    if friendly:
        candidates.add(normalize_app_name(friendly))
    for exe_key, friendly_name in {**FRIENDLY_APP_NAMES, **PROCESS_NAME_ALIASES}.items():
        if normalize_app_name(friendly_name) in candidates:
            candidates.add(exe_key)
    return candidates


def _close_windows_for(process_ids):
    """Ask every visible window owned by these processes to close (lets apps save first)."""
    try:
        import win32con
        import win32gui
        import win32process
    except ImportError:
        return False

    asked = []

    def callback(handle, _extra):
        try:
            if not win32gui.IsWindowVisible(handle) or win32gui.GetWindow(handle, win32con.GW_OWNER):
                return True
            _, process_id = win32process.GetWindowThreadProcessId(handle)
            if process_id in process_ids:
                win32gui.PostMessage(handle, win32con.WM_CLOSE, 0, 0)
                asked.append(process_id)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        return False
    return bool(asked)


def _stop_processes(processes):
    """Close windows, then terminate, then force kill. Returns processes still alive."""
    import psutil

    if _close_windows_for({process.pid for process in processes}):
        time.sleep(1.2)

    stubborn = []
    for process in processes:
        try:
            if process.is_running():
                stubborn.append(process)
        except psutil.Error:
            continue

    if stubborn:
        for process in stubborn:
            try:
                process.terminate()
            except psutil.Error:
                pass
        _gone, stubborn = psutil.wait_procs(stubborn, timeout=3)

    if stubborn:
        for process in stubborn:
            try:
                process.kill()
            except psutil.Error:
                pass
        _gone, stubborn = psutil.wait_procs(stubborn, timeout=2)

    return list(stubborn)


def _close_result_message(labels, forced):
    if len(labels) == 1:
        message = f"Closed {labels[0]}."
    else:
        message = f"Closed {', '.join(labels[:-1])} and {labels[-1]}."
    if forced:
        message += " It wasn't responding, so I forced it closed."
    return {"ok": True, "message": message, "apps": labels}


def close_application(requested_name):
    """Close every running process whose name matches the spoken app name."""
    try:
        import psutil
    except ImportError:
        return {"ok": False, "message": "psutil is not installed on this computer."}

    candidates = _close_name_candidates(requested_name)
    if not candidates:
        return {"ok": False, "message": f"I didn't catch an app name in '{requested_name}'."}

    blocked = sorted(candidates & PROTECTED_PROCESS_NAMES)
    if blocked:
        label = _friendly_process_name(blocked[0])
        return {"ok": False, "message": f"I won't close {label} — Windows needs it running."}

    matches = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            key = (process.info.get("name") or "").removesuffix(".exe").strip().lower()
            if not key or key in PROTECTED_PROCESS_NAMES or process.pid == os.getpid():
                continue
            if normalize_app_name(key) in candidates:
                matches.append(process)
        except (psutil.Error, OSError):
            continue

    if not matches:
        return {"ok": False, "message": f"{requested_name.strip().capitalize()} isn't running right now."}

    labels = []
    for process in matches:
        key = (process.info.get("name") or "").removesuffix(".exe").strip().lower()
        label = _friendly_process_name(key)
        if label not in labels:
            labels.append(label)

    stubborn = _stop_processes(matches)
    return _close_result_message(labels, bool(stubborn))


def close_active_app():
    """Close whichever app window is in the foreground right now."""
    try:
        import win32gui
        import win32process
    except ImportError:
        return {"ok": False, "message": "pywin32 is not installed on this computer."}

    try:
        window = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(window)
        if not window or not title:
            return {"ok": False, "message": "I can't see a window to close right now."}
        _, process_id = win32process.GetWindowThreadProcessId(window)
    except Exception as error:
        return {"ok": False, "message": f"I couldn't read the active window: {error}"}

    if re.search(r"\b(lunar|jarvis)\b", title, flags=re.IGNORECASE):
        return {"ok": False, "message": "That's Lunar itself. Tell me which other app to close."}

    try:
        import psutil
        process = psutil.Process(process_id)
        key = (process.name() or "").removesuffix(".exe").strip().lower()
        if key in PROTECTED_PROCESS_NAMES:
            return {"ok": False, "message": "I can't close a core Windows process."}
        # Store apps run inside ApplicationFrameHost, so the window title is the real app name
        label = title.strip() if key == "applicationframehost" and title.strip() else _friendly_process_name(key)
    except Exception:
        return {"ok": False, "message": "I couldn't identify the app in front of you."}

    stubborn = _stop_processes([process])
    return _close_result_message([label], bool(stubborn))


def close_command(command):
    """Handle close/quit/exit/kill phrases; returns a result dict or None if not matched."""
    if command in CLOSE_CURRENT_PHRASES:
        return close_active_app()
    if command in CLOSE_BARE_PHRASES:
        return {"ok": False, "message": "Which app should I close? Try saying close notepad."}

    for prefix in CLOSE_PREFIXES:
        if not command.startswith(prefix):
            continue
        target = command[len(prefix):].strip()
        stripping = True
        while stripping:
            stripping = False
            for filler in CLOSE_FILLER_WORDS:
                if target.startswith(filler) and len(target) > len(filler):
                    target = target[len(filler):].strip()
                    stripping = True
                    break
        if not target:
            return {"ok": False, "message": "Which app should I close? Try saying close notepad."}
        for trailing in CLOSE_TRAILING_WORDS:
            if target.endswith(trailing):
                target = target[:-len(trailing)].strip()
                break
        if target in ("app", "program", "window", "app for me", "one") or re.match(
            r"^(?:app|program|window)\b", target
        ):
            return close_active_app()
        return close_application(target)

    return None


# ---------------- Speech-to-text (dictation) ----------------
_PUNCT_RULES = [
    (re.compile(r"\bnew paragraph\b", re.I), "\n\n"),
    (re.compile(r"\bnew line\b", re.I), "\n"),
    (re.compile(r"\bfull stop\b", re.I), "."),
    (re.compile(r"\bperiod\b", re.I), "."),
    (re.compile(r"\bcomma\b", re.I), ","),
    (re.compile(r"\bquestion mark\b", re.I), "?"),
    (re.compile(r"\bexclamation (?:mark|point)\b", re.I), "!"),
    (re.compile(r"\bcolon\b", re.I), ":"),
    (re.compile(r"\bsemicolon\b", re.I), ";"),
    (re.compile(r"\bdash\b", re.I), " - "),
    (re.compile(r"\bhyphen\b", re.I), "-"),
    (re.compile(r"\bopen (?:quote|paren|bracket)\b", re.I), '"'),
    (re.compile(r"\bclose (?:quote|paren|bracket)\b", re.I), '"'),
]


def _spoken_punctuation(text):
    """Convert spoken punctuation words and capitalize sentence starts."""
    for pattern, replacement in _PUNCT_RULES:
        text = pattern.sub(replacement, text)
    # tidy spacing: no space before punctuation, one space after, none around newlines
    text = re.sub(r"[ \t]+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,.!?;:])(?=[A-Za-z0-9])", r"\1 ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    out = []
    capitalize_next = True
    for char in text:
        if capitalize_next and char.isalpha():
            out.append(char.upper())
            capitalize_next = False
        else:
            out.append(char)
        if char in ".!?\n":
            capitalize_next = True
    return "".join(out)


def type_text(text):
    """Type text into the focused field via SendInput unicode events."""
    import ctypes
    from ctypes import wintypes

    if not text or not text.strip():
        return {"ok": False, "message": "What should I write?"}

    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", PUL),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_ubyte * 32)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]

    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    INPUT_KEYBOARD = 1
    VK_RETURN = 0x0D
    user32 = ctypes.windll.user32

    def press_enter():
        """Send a real Enter key with scan code (plain synthetic VK is ignored by some editors)."""
        inputs = (INPUT * 2)()
        inputs[0].type = INPUT_KEYBOARD
        inputs[0].ki = KEYBDINPUT(VK_RETURN, 0x1C, 0, 0, None)
        inputs[1].type = INPUT_KEYBOARD
        inputs[1].ki = KEYBDINPUT(VK_RETURN, 0x1C, KEYEVENTF_KEYUP, 0, None)
        return user32.SendInput(2, inputs, ctypes.sizeof(INPUT))

    def send_char(char):
        # down+up must go as ONE batched SendInput - separate calls get dropped by WinUI apps
        inputs = (INPUT * 2)()
        inputs[0].type = INPUT_KEYBOARD
        inputs[0].ki = KEYBDINPUT(0, ord(char), KEYEVENTF_UNICODE, 0, None)
        inputs[1].type = INPUT_KEYBOARD
        inputs[1].ki = KEYBDINPUT(0, ord(char), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)
        return user32.SendInput(2, inputs, ctypes.sizeof(INPUT))

    sent = 0
    for char in text:
        if ord(char) > 0xFFFF:  # characters outside the BMP are not typable
            continue
        if char in "\n\r":
            if press_enter():
                sent += 1
            time.sleep(0.05)
            continue
        if send_char(char):
            sent += 1
        time.sleep(0.03)  # slow down: fast unicode floods get scrambled by some apps/IMEs

    if not sent:
        return {"ok": False, "message": "I couldn't type that here."}
    return {"ok": True, "message": f"Wrote it down. ({sent} characters typed)"}


DICTATION_STOP_PHRASES = (
    "stop dictation", "stop writing", "stop typing", "stop dictating",
    "dictation off", "end dictation",
)


def start_dictation():
    """Enable continuous dictation while hands-free mode is active."""
    state = CONTROLLER.get_state()
    if not state.get("wake_enabled"):
        return {"ok": False, "message": "Enable hands-free mode first, then say start dictation."}
    CONTROLLER._set_state(
        dictation_enabled=True,
        status="ready",
        message="Dictation on. Speak and I will type it. Say stop dictation to end.",
        speech_text="Dictation on. Speak and I will type it. Say stop dictation to end.",
    )
    return {"ok": True, "message": "Dictation on. Speak and I will type it. Say stop dictation to end."}


def stop_dictation():
    """Disable continuous dictation."""
    CONTROLLER._set_state(
        dictation_enabled=False,
        status="ready",
        message="Dictation stopped.",
        speech_text="Dictation stopped.",
    )
    return {"ok": True, "message": "Dictation stopped."}


def dictation_command(command, original, voice):
    """Handle write/type/dictate phrases; returns result dict or None."""
    if command in ("start dictation", "begin dictation", "dictation mode", "start writing", "start typing"):
        return start_dictation()
    if command in DICTATION_STOP_PHRASES:
        return stop_dictation()

    for starter in ("write ", "type ", "dictate "):
        if command.startswith(starter):
            payload = original[len(starter):].strip()
            if voice:
                payload = _spoken_punctuation(payload)
            return type_text(payload)
    return None


VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_STOP = 0xB2
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1


def press_media_key(vk_code):
    """Send a virtual media key to the operating system."""
    import ctypes
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


def press_play_key():
    """Send a virtual play/pause media key so the OS resumes the last track."""
    press_media_key(VK_MEDIA_PLAY_PAUSE)


def media_control(action):
    """Control playback in the active media player."""
    key_map = {
        "play": VK_MEDIA_PLAY_PAUSE,
        "pause": VK_MEDIA_PLAY_PAUSE,
        "stop": VK_MEDIA_STOP,
        "next": VK_MEDIA_NEXT_TRACK,
        "previous": VK_MEDIA_PREV_TRACK,
    }
    messages = {
        "play": "Playing your music.",
        "pause": "Music paused.",
        "stop": "Music stopped.",
        "next": "Skipping to the next track.",
        "previous": "Going back to the previous track.",
        "replay": "Playing the same song again.",
    }
    try:
        if action == "replay":
            press_media_key(VK_MEDIA_PREV_TRACK)
            time.sleep(0.4)
            press_media_key(VK_MEDIA_PLAY_PAUSE)
        else:
            press_media_key(key_map[action])
    except Exception as error:
        return {"ok": False, "message": f"I couldn't control the media player: {error}"}
    return {"ok": True, "message": messages[action]}


FRIENDLY_APP_NAMES = {
    "code": "VS Code",
    "msedge": "Microsoft Edge",
    "chrome": "Chrome",
    "firefox": "Firefox",
    "winword": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpnt": "Microsoft PowerPoint",
    "outlook": "Outlook",
    "onenote": "OneNote",
    "teams": "Microsoft Teams",
    "spotify": "Spotify",
    "notepad": "Notepad",
    "devenv": "Visual Studio",
    "pycharm64": "PyCharm",
    "idea64": "IntelliJ IDEA",
    "cmd": "Command Prompt",
    "windowsterminal": "Windows Terminal",
    "applicationframehost": "a Windows app",
    "textinputhost": "Windows text input",
    "searchhost": "Windows search",
    "shellexperiencehost": "the Windows shell",
    "startmenuexperiencehost": "the Start menu",
}

ACTIVE_WINDOW_TRACKER = {"app": None, "since": None}


def check_battery_status():
    """Report battery percentage, charging state, and low-battery warnings via psutil."""
    try:
        import psutil
    except ImportError:
        return {"ok": False, "message": "psutil is not installed on this computer."}

    battery = psutil.sensors_battery()
    if battery is None:
        return {"ok": False, "message": "This PC doesn't report a battery. It may be a desktop."}

    percent = round(battery.percent)
    plugged = bool(battery.power_plugged)

    if plugged:
        if percent >= 95:
            message = f"Battery is fully charged at {percent} percent, and the charger is connected."
        else:
            message = f"Battery is at {percent} percent and charging."
        return {"ok": True, "message": message, "percent": percent, "charging": True}

    if percent <= 20:
        message = f"Warning: battery is low at {percent} percent. Plug in the charger."
    elif percent <= 40:
        message = f"Battery is at {percent} percent. Consider charging soon."
    else:
        seconds_left = getattr(battery, "secsleft", None)
        if isinstance(seconds_left, int) and seconds_left > 0:
            hours, remainder = divmod(seconds_left, 3600)
            minutes = remainder // 60
            message = f"Battery is at {percent} percent, about {hours} hours and {minutes} minutes remaining."
        else:
            message = f"Battery is at {percent} percent and discharging."
    return {"ok": True, "message": message, "percent": percent, "charging": False}


def check_cpu_ram_usage():
    """Report CPU load and memory usage, warning when the system is overloaded."""
    try:
        import psutil
    except ImportError:
        return {"ok": False, "message": "psutil is not installed on this computer."}

    cpu_percent = psutil.cpu_percent(interval=0.5)
    memory = psutil.virtual_memory()
    ram_percent = memory.percent
    ram_used_gb = (memory.total - memory.available) / (1024 ** 3)
    ram_total_gb = memory.total / (1024 ** 3)

    parts = [
        f"CPU is at {round(cpu_percent)} percent",
        f"RAM is using {ram_used_gb:.1f} of {ram_total_gb:.1f} gigabytes, that is {round(ram_percent)} percent",
    ]
    if cpu_percent >= 85:
        parts.append("The processor is overloaded. You may want to close heavy apps.")
    if ram_percent >= 90:
        parts.append("Memory is nearly full.")
    return {
        "ok": True,
        "message": ". ".join(parts) + ".",
        "cpu": round(cpu_percent),
        "ram": round(ram_percent),
    }


def check_unread_emails():
    """Count unread emails in the local Outlook desktop inbox via pywin32."""
    try:
        import win32com.client
    except ImportError:
        return {"ok": False, "message": "pywin32 is not installed on this computer."}
    try:
        namespace = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        inbox = namespace.GetDefaultFolder(6)  # 6 = olFolderInbox
        unread = int(inbox.UnReadItemCount)
        if unread == 0:
            return {"ok": True, "message": "Your inbox is clear. No unread emails.", "unread": 0}
        suffix = "" if unread == 1 else "s"
        return {
            "ok": True,
            "message": f"You have {unread} unread email{suffix} in your inbox.",
            "unread": unread,
        }
    except Exception:
        return {
            "ok": False,
            "message": "I couldn't reach Outlook. Make sure the desktop app is installed and signed in.",
        }


def check_teams_unread(open_chat=True):
    """Count unread Microsoft Teams messages and optionally jump into the unread chat.

    Uses Windows UI Automation (pywinauto) because Teams exposes no local API.
    Strategy: find the Teams window, read unread count from its title badge
    (e.g. '(4) Microsoft Teams') or from unread badge elements, focus it,
    and navigate to the Chat list.
    """
    # 1. Is Teams running? If not, try to launch it.
    teams_running = False
    try:
        import psutil
        for proc in psutil.process_iter(attrs=["name"]):
            name = (proc.info.get("name") or "").lower()
            if name.startswith(("ms-teams", "teams")):
                teams_running = True
                break
    except Exception:
        pass

    if not teams_running:
        launch = open_application("teams")
        if not launch.get("ok"):
            return {"ok": False, "message": "Microsoft Teams isn't installed on this PC."}
        time.sleep(9)  # Teams is slow to reach the inbox

    # 2. Locate the Teams window via UI Automation.
    try:
        from pywinauto import Desktop
    except ImportError:
        return {"ok": False, "message": "pywinauto is not installed on this computer."}

    teams_window = None
    unread_from_title = None
    try:
        candidates = []
        for window in Desktop(backend="uia").windows():
            title = window.window_text() or ""
            if "teams" not in title.lower():
                continue
            match = re.search(r"\((\d{1,2})\)", title)
            if match:
                unread_from_title = int(match.group(1))
                candidates.insert(0, window)  # windows with a badge are the main app
            else:
                candidates.append(window)
        if candidates:
            teams_window = candidates[0]
    except Exception:
        teams_window = None

    if teams_window is None:
        return {
            "ok": False,
            "message": "I couldn't find a Microsoft Teams window. Open Teams and try again.",
        }

    # 3. Read unread count: title badge first, else scan badge elements once.
    unread_count = unread_from_title
    first_unread_item = None
    if unread_count is None:
        try:
            badge_total = 0
            found_any_badge = False
            for element in teams_window.descendants():
                try:
                    name = (element.element_info.name or "").strip()
                except Exception:
                    continue
                if not name:
                    continue
                badge_match = re.fullmatch(r"(\d{1,2})\s+unread", name, flags=re.IGNORECASE)
                if badge_match:
                    badge_total += int(badge_match.group(1))
                    found_any_badge = True
                    if first_unread_item is None and element.element_info.control_type in (
                        "ListItem", "Button", "TabItem",
                    ):
                        first_unread_item = element
                    continue
                if name.lower() in ("unread", "marked as unread") and first_unread_item is None:
                    first_unread_item = element
            if found_any_badge:
                unread_count = badge_total
        except Exception:
            pass

    # 4. Bring Teams forward and open the chat list / first unread chat.
    opened_chat = False
    try:
        teams_window.set_focus()
        time.sleep(0.6)
        teams_window.type_keys("^1", pause=0.1)  # Ctrl+1 = Chat section
        time.sleep(1.2)
        if open_chat and first_unread_item is not None:
            try:
                first_unread_item.select()
                opened_chat = True
            except Exception:
                opened_chat = False
    except Exception:
        pass

    # 5. Speak the result.
    if unread_count is None:
        return {
            "ok": True,
            "message": "Teams is open, but I couldn't read the unread badge. The chat list is in front of you.",
            "opened_chat": opened_chat,
        }
    if unread_count == 0:
        return {"ok": True, "message": "You're all caught up. No unread messages in Teams.", "unread": 0}

    suffix = "" if unread_count == 1 else "s"
    message = f"You have {unread_count} unread message{suffix} in Microsoft Teams."
    message += " I've opened the unread chat for you." if opened_chat else " Your chat list is open."
    return {"ok": True, "message": message, "unread": unread_count, "opened_chat": opened_chat}


def _find_phone_call_window():
    """Find the Phone Link window handling a call (incoming or active)."""
    try:
        from pywinauto import Desktop
    except ImportError:
        return None

    ranked = []
    try:
        for window in Desktop(backend="uia").windows():
            title = (window.window_text() or "").strip()
            lowered = title.lower()
            if "incoming call" in lowered:
                ranked.insert(0, (0, window))  # best: dedicated call window
            elif "phone link" in lowered or "your phone" in lowered:
                ranked.append((1, window))
    except Exception:
        pass
    if not ranked:
        return None, False
    return ranked[0][1], ranked[0][0] == 0


def _invoke_call_button(window, keywords):
    """Click the first button in the window whose name matches any keyword."""
    for element in window.descendants():
        try:
            name = (element.element_info.name or "").strip().lower()
            control_type = element.element_info.control_type
        except Exception:
            continue
        if control_type == "Button" and name and any(word in name for word in keywords):
            element.invoke()
            return True
    return False


def control_phone_call(action):
    """Answer, decline, or end a phone call via the Phone Link app."""
    try:
        from pywinauto import Desktop  # noqa: F401
    except ImportError:
        return {"ok": False, "message": "pywinauto is not installed on this computer."}

    window, call_window_active = _find_phone_call_window()
    if window is None:
        # Phone Link may be closed; try to bring it up quickly.
        try:
            open_application("phone link")
            time.sleep(4)
            window, call_window_active = _find_phone_call_window()
        except Exception:
            window, call_window_active = None, False
    if window is None:
        return {
            "ok": False,
            "message": "I can't see an active or incoming call in Phone Link. Is your phone connected?",
        }

    keywords = {
        "answer": ("accept", "answer", "pick up"),
        "decline": ("decline", "reject", "deny"),
        "end": ("end call", "hang up", "end"),
    }[action]
    messages = {
        "answer": "Call answered. Go ahead, sir.",
        "decline": "Call declined.",
        "end": "Call ended.",
    }

    try:
        window.set_focus()
        time.sleep(0.4)
        if _invoke_call_button(window, keywords):
            return {"ok": True, "message": messages[action]}
        if not call_window_active:
            return {"ok": False, "message": "There's no incoming or active call right now."}
        return {
            "ok": False,
            "message": "A call window is open but I couldn't reach its buttons. Please use the window directly.",
        }
    except Exception as error:
        return {"ok": False, "message": f"I couldn't control the call: {error}"}


def _extract_caller_info(window):
    """Best-effort caller name/number from the incoming call window."""
    title = (window.window_text() or "").strip()
    for separator in ("-", "\u2013", ",", ":"):
        if separator in title:
            tail = title.split(separator, 1)[1].strip()
            if tail and "incoming call" not in tail.lower():
                return tail

    number = None
    name = None
    try:
        for element in window.descendants():
            try:
                if element.element_info.control_type != "Text":
                    continue
                text = (element.element_info.name or "").strip()
            except Exception:
                continue
            if not text or "incoming call" in text.lower():
                continue
            digits = re.sub(r"\D", "", text)
            if number is None and len(digits) >= 7:
                number = text
            if name is None and 1 < len(text) < 40 and not text.isdigit() and len(digits) < 7:
                name = text
    except Exception:
        pass
    if name and number:
        return f"{name} ({number})"
    return name or number or None


_CALL_WATCHER = {"key": None, "announced": False}


def _find_incoming_call_title():
    """Title of a Phone Link call window, found with plain Win32 window listing.

    Enumerating every window through UI Automation costs most of a second, so it
    is reserved for reading caller details once a call has actually been spotted.
    """
    try:
        import win32gui
    except ImportError:
        return None

    found = []

    def callback(handle, _extra):
        try:
            if win32gui.IsWindowVisible(handle):
                title = win32gui.GetWindowText(handle) or ""
                if "incoming call" in title.lower():
                    found.append(title)
                    return False        # stop enumerating
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        return None
    return found[0] if found else None


def _find_incoming_call_window():
    """UI Automation handle for the call window; only called once per call."""
    try:
        from pywinauto import Desktop
        for top_window in Desktop(backend="uia").windows():
            if "incoming call" in (top_window.window_text() or "").lower():
                return top_window
    except Exception:
        pass
    return None


def _incoming_call_watcher():
    """Watch for Phone Link incoming-call windows and announce them once per call."""
    while True:
        window_key = _find_incoming_call_title()

        if window_key is not None:
            if not _CALL_WATCHER["announced"]:
                _CALL_WATCHER["announced"] = True
                _CALL_WATCHER["key"] = window_key
                call_window = _find_incoming_call_window()
                caller = _extract_caller_info(call_window) if call_window is not None else None
                message = f"Incoming call from {caller}." if caller else "Incoming call."
                try:
                    with CONTROLLER._lock:
                        CONTROLLER._state.update({
                            "status": "ready",
                            "message": message,
                            "heard": "",
                            "speech_text": message,
                            "revision": CONTROLLER._state["revision"] + 1,
                            "ok": True,
                            "incoming_call": True,
                        })
                except Exception:
                    pass
        elif _CALL_WATCHER["announced"]:
            _CALL_WATCHER["announced"] = False
            _CALL_WATCHER["key"] = None
            try:
                CONTROLLER._set_state(incoming_call=False)
            except Exception:
                pass
        time.sleep(2)


def get_current_active_window():
    """Return the app and window the user is currently focused on, with session duration."""
    try:
        import win32gui
        import win32process
    except ImportError:
        return {"ok": False, "message": "pywin32 is not installed on this computer."}

    try:
        window_handle = win32gui.GetForegroundWindow()
        window_title = win32gui.GetWindowText(window_handle)
        if not window_title:
            return {"ok": False, "message": "I couldn't read the active window right now."}

        _, process_id = win32process.GetWindowThreadProcessId(window_handle)
        app_name = None
        try:
            import psutil
            executable = psutil.Process(process_id).name()
            app_key = executable.removesuffix(".exe").strip().lower()
            app_name = FRIENDLY_APP_NAMES.get(app_key, executable.removesuffix(".exe").strip())
        except (Exception, psutil.Error):
            app_name = None

        now = time.time()
        if ACTIVE_WINDOW_TRACKER["app"] != app_name:
            ACTIVE_WINDOW_TRACKER["app"] = app_name
            ACTIVE_WINDOW_TRACKER["since"] = now
        minutes_on_app = int((now - (ACTIVE_WINDOW_TRACKER["since"] or now)) // 60)

        if app_name:
            message = f"You're currently using {app_name}"
            if minutes_on_app >= 5:
                message += f" — you've been on it for about {minutes_on_app} minutes"
            message += f"{', with ' + window_title[:70] + ' open.' if window_title and window_title != app_name else '.'}"
        else:
            message = f"The active window is: {window_title[:90]}"
        return {"ok": True, "message": message, "app": app_name, "minutes": minutes_on_app}
    except Exception as error:
        return {"ok": False, "message": f"I couldn't check the active window: {error}"}


def open_last_song():
    """Open the media player and resume the last played track."""
    try:
        player = find_installed_app("media player")
        player_name = player["Name"] if player else None
    except (LookupError, OSError, subprocess.SubprocessError, json.JSONDecodeError):
        player = None
        player_name = None

    launched = False
    try:
        if player:
            app_id = player.get("AppID", "")
            if os.path.isfile(app_id):
                subprocess.Popen([app_id], creationflags=CREATE_NO_WINDOW)
            else:
                subprocess.Popen(
                    ["explorer.exe", f"shell:AppsFolder\\{app_id}"],
                    creationflags=CREATE_NO_WINDOW,
                )
            launched = True
    except (OSError, subprocess.SubprocessError):
        launched = False

    if not launched:
        player_name = "Spotify"
        spotify_candidates = []
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            spotify_candidates.append(Path(local_app_data) / "Spotify" / "spotify.exe")
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        spotify_candidates.append(Path(program_files) / "Spotify" / "spotify.exe")
        spotify_exe = shutil.which("spotify.exe")
        if spotify_exe:
            spotify_candidates.append(Path(spotify_exe))
        for candidate in spotify_candidates:
            if candidate.is_file():
                try:
                    subprocess.Popen([str(candidate)], close_fds=True, creationflags=CREATE_NO_WINDOW)
                    launched = True
                    break
                except (OSError, subprocess.SubprocessError):
                    continue

    if not launched:
        return {
            "ok": False,
            "message": "I couldn't find a media player. Install Windows Media Player or Spotify and try again.",
        }

    try:
        time.sleep(2.5)
        press_play_key()
    except Exception:
        pass

    return {"ok": True, "message": f"Playing your last song in {player_name}.", "app": player_name}


def _open_in_default_browser(url):
    """Open a URL as a new tab in the system default browser."""
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception as error:
        print(f"[browser] could not open {url}: {error}", flush=True)
        return False


def _page_result(url, message, voice):
    """Hand a web page to the browser already showing Lunar.

    A typed command travels back out through the page, which opens the link with
    window.open() so it lands as a new tab beside Lunar, in that same browser.
    Hands-free commands have no page gesture to borrow, so they go to the default
    browser - the same one main() opened Lunar's own page with.
    """
    if voice:
        if not _open_in_default_browser(url):
            return {"ok": False, "message": "I couldn't open a browser for that."}
        return {"ok": True, "message": message}
    return {"ok": True, "message": message, "url": url}


def normalize_spoken_url(target):
    target = target.strip()
    target = re.sub(r"\b(https?)\s+colon\s+slash\s+slash\b", r"\1://", target, flags=re.IGNORECASE)
    target = re.sub(r"\bwww\s+dot\s+", "www.", target, flags=re.IGNORECASE)
    target = re.sub(r"\s+dot\s+", ".", target, flags=re.IGNORECASE)
    target = re.sub(r"\s+slash\s+", "/", target, flags=re.IGNORECASE)
    target = re.sub(r"\s+question mark\s+", "?", target, flags=re.IGNORECASE)
    target = re.sub(r"\s+equals\s+", "=", target, flags=re.IGNORECASE)
    target = re.sub(r"\s+ampersand\s+", "&", target, flags=re.IGNORECASE)
    return target.strip(" .,!?\t\r\n")


def open_search_in_browser(command, voice=False):
    prefixes = (
        "search on google for ",
        "search google for ",
        "google search for ",
        "google search ",
        "search for ",
        "search ",
        "look up ",
    )
    lowered = command.lower()
    query = None
    for prefix in prefixes:
        if lowered.startswith(prefix):
            query = command[len(prefix):].strip()
            break

    if query is None:
        if lowered in ("search", "google search", "search for"):
            return {"ok": False, "message": "Tell me what you'd like me to search for."}
        return None

    query = re.sub(
        r"\s+(?:in|on|using)\s+(?:(?:google\s+)?chrome|google)[.!?]*$",
        "",
        query,
        flags=re.IGNORECASE,
    ).strip().strip("\"'")
    if not query:
        return {"ok": False, "message": "Tell me what you'd like me to search for."}

    search_url = f"https://www.google.com/search?{urlencode({'q': query})}"
    return _page_result(search_url, f"Searching Google for {query} in your browser.", voice)


def open_url_in_browser(command, voice=False):
    prefixes = ("open ", "go to ", "visit ", "navigate to ", "browse to ")
    explicit_open = False
    target = command
    for prefix in prefixes:
        if command.lower().startswith(prefix):
            target = command[len(prefix):].strip()
            explicit_open = True
            break

    target = re.sub(r"\s+(?:in|on|using)\s+(?:google\s+)?chrome[.!?]*$", "", target, flags=re.IGNORECASE).strip()
    target = normalize_spoken_url(target)
    # Spoken short names ("open yt") resolve here. App names are deliberately
    # absent so open_application() still gets a chance to launch them.
    common_sites = {
        "amazon": "https://www.amazon.com",
        "chatgpt": "https://chatgpt.com",
        "drive": "https://drive.google.com",
        "fb": "https://www.facebook.com",
        "facebook": "https://www.facebook.com",
        "gh": "https://github.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "google": "https://www.google.com",
        "ig": "https://www.instagram.com",
        "insta": "https://www.instagram.com",
        "instagram": "https://www.instagram.com",
        "linkedin": "https://www.linkedin.com",
        "netflix": "https://www.netflix.com",
        "news": "https://news.google.com/",
        "reddit": "https://www.reddit.com",
        "stackoverflow": "https://stackoverflow.com",
        "twitter": "https://x.com",
        "wa": "https://web.whatsapp.com",
        "whatsapp": "https://web.whatsapp.com",
        "whatsapp web": "https://web.whatsapp.com",
        "wiki": "https://www.wikipedia.org",
        "wikipedia": "https://www.wikipedia.org",
        "x": "https://x.com",
        "yt": "https://www.youtube.com",
        "ytb": "https://www.youtube.com",
        "youtube": "https://www.youtube.com",
    }
    if explicit_open and target.lower() in common_sites:
        target = common_sites[target.lower()]

    has_web_scheme = target.lower().startswith(("http://", "https://"))
    if not has_web_scheme:
        if not explicit_open and any(character.isspace() for character in target):
            return None
        host = target.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
        if "." not in host:
            return None
        target = f"https://{target}"

    try:
        parsed = urlsplit(target)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or not parsed.hostname:
            return {"ok": False, "message": "Please use a valid HTTP or HTTPS website address."}
    except ValueError:
        return {"ok": False, "message": "That website address doesn't look valid."}

    return _page_result(target, f"Opening {parsed.netloc} in your browser.", voice)


def _clean_information_command(command):
    cleaned = str(command).lower().replace("’", "'").replace("â€™", "'").strip(" .,!?:;\"'")
    request_prefixes = (
        "please ", "tell me ", "show me ", "give me ", "read me ",
        "what is ", "what's ", "check ", "get ", "find ", "open ",
        "search for ", "search ",
    )
    changed = True
    while changed:
        changed = False
        for prefix in request_prefixes:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                changed = True
                break
    return re.sub(r"\s+", " ", cleaned).strip(" .,!?:;\"'")


def open_news_in_browser(command, voice=False):
    # "search for space news" is a search, not a request for news about space.
    # News is checked before search in handle_command, so hand these back.
    if str(command).lower().startswith(("search ", "look up ", "google ")):
        return None

    phrase = _clean_information_command(command)
    phrase = re.sub(r"\b(?:today's|todays|today|latest|the)\b", " ", phrase)
    phrase = re.sub(r"\s+", " ", phrase).strip()

    topic = None
    if phrase in ("news", "headlines", "top stories"):
        pass
    else:
        match = re.fullmatch(
            r"(?:news|headlines|top stories)\s+(?:about|on|in|for)\s+(.+)",
            phrase,
        )
        if match:
            topic = match.group(1).strip()
        else:
            match = re.fullmatch(r"(.+?)\s+(?:news|headlines)", phrase)
            if match:
                topic = match.group(1).strip()
            else:
                return None

    if topic:
        url = f"https://news.google.com/search?{urlencode({'q': topic})}"
        return _page_result(url, f"Opening the latest news about {topic} in your browser.", voice)
    return _page_result("https://news.google.com/", "Opening the latest news in your browser.", voice)


def open_weather_in_browser(command, voice=False):
    phrase = _clean_information_command(command)
    phrase = re.sub(r"^(?:the\s+)+", "", phrase)
    phrase = re.sub(r"^(?:today'?s?|today)\s+", "", phrase)
    phrase = re.sub(r"\s+(?:for today|today|right now)$", "", phrase)
    phrase = re.sub(r"\s+today\s+", " ", phrase)
    phrase = re.sub(r"\s+like$", "", phrase).strip()
    if not phrase.startswith("weather"):
        return None

    location = phrase[len("weather"):].strip()
    if location.startswith(("in ", "at ", "for ")):
        location = location.split(" ", 1)[1].strip()
    elif location:
        return None

    query = "weather today" + (f" in {location}" if location else "")
    url = f"https://www.google.com/search?{urlencode({'q': query})}"
    message = (
        f"Opening today's weather for {location} in your browser."
        if location else "Opening today's local weather in your browser."
    )
    return _page_result(url, message, voice)


class WhatsAppInbox:
    MAX_MESSAGES = 15
    MAX_MESSAGE_CHARS = 2000
    SNAPSHOT_MAX_AGE_SECONDS = 300

    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot = None

    def update(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Invalid WhatsApp snapshot")

        chat = re.sub(r"\s+", " ", str(payload.get("chat", "WhatsApp chat"))).strip()[:100]
        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            raise ValueError("WhatsApp messages must be a list")

        messages = []
        for item in raw_messages[-self.MAX_MESSAGES:]:
            if not isinstance(item, dict):
                continue
            direction = item.get("direction")
            text = item.get("text")
            if direction not in ("incoming", "outgoing") or not isinstance(text, str):
                continue
            text = re.sub(r"\s+", " ", text).strip()[:self.MAX_MESSAGE_CHARS]
            if text:
                messages.append({"direction": direction, "text": text})

        snapshot = {
            "chat": chat or "WhatsApp chat",
            "messages": messages,
            "received_at": time.time(),
        }
        with self._lock:
            self._snapshot = snapshot
        return len(messages)

    def get_snapshot(self):
        with self._lock:
            snapshot = self._snapshot
            if snapshot is None:
                return None
            if time.time() - snapshot["received_at"] > self.SNAPSHOT_MAX_AGE_SECONDS:
                self._snapshot = None
                return None
            return {
                "chat": snapshot["chat"],
                "messages": [dict(message) for message in snapshot["messages"]],
                "received_at": snapshot["received_at"],
            }


WHATSAPP_INBOX = WhatsAppInbox()


def read_whatsapp_messages():
    snapshot = WHATSAPP_INBOX.get_snapshot()
    if snapshot is None:
        return {
            "ok": False,
            "message": "Open WhatsApp Web in Chrome, keep a chat visible, and make sure the Lunar Reader extension is enabled.",
        }

    incoming = [item["text"] for item in snapshot["messages"] if item["direction"] == "incoming"]
    if not incoming:
        return {
            "ok": False,
            "message": f"I don't see any recent incoming text messages in the open {snapshot['chat']} chat.",
        }

    latest = [message[:500] for message in incoming[-3:]]
    spoken_messages = ". ".join(latest)
    return {
        "ok": True,
        "message": f"Recent messages in {snapshot['chat']}: {spoken_messages}",
        "chat": snapshot["chat"],
        "messages": latest,
    }


def handle_command(text, voice=False):
    raw_text = str(text)  # keep newlines intact for dictation
    original_command = " ".join(str(text).split())
    command = original_command.lower()
    if not command:
        return {"ok": False, "message": "I didn't receive a command."}

    if command in ("hello", "hi"):
        return {"ok": True, "message": "Hello. I'm ready."}

    if command in ("how are you", "how r u", "how are u", "how r you"):
        return {"ok": True, "message": "All systems are functioning normally."}

    if command == "exit":
        return {"ok": True, "message": "Lunar is online. Close this window to leave."}

    homework_command = command.replace("’", "'").strip(" .,!?:;")
    if homework_command == "homework":
        if not HOMEWORK_URL:
            return {
                "ok": False,
                "message": (
                    "I don't have a homework link set. Set the "
                    f"{HOMEWORK_ENV_VAR} environment variable to your school portal."
                ),
            }
        return open_url_in_browser(f"open {HOMEWORK_URL}", voice)

    if command in (
        "play my last song",
        "play the last song",
        "play last song",
        "play my last track",
        "play the last track",
        "play last track",
        "play my music",
        "play music",
        "resume music",
        "resume my music",
        "resume song",
        "resume my song",
        "resume the song",
        "continue my music",
        "continue the music",
    ):
        return open_last_song()

    media_actions = (
        ("play", (
            "start music", "start the music", "start my music",
            "start playing", "start playing music", "start the song", "start my song",
            "play", "play song", "play the song", "play my song", "play some music",
        )),
        ("pause", (
            "pause", "pause music", "pause the music", "pause my music",
            "pause song", "pause the song", "pause my song",
        )),
        ("stop", (
            "stop", "stop music", "stop the music", "stop my music",
            "stop song", "stop the song", "stop my song", "stop playing",
        )),
        ("next", (
            "next", "next song", "next track", "next music",
            "play next song", "play the next song", "skip song", "skip the song",
            "skip track", "skip to the next song", "forward the song",
        )),
        ("previous", (
            "previous song", "previous track", "play previous song", "play the previous song",
            "go back a song", "go to the previous song", "go back one song",
            "rewind song", "back song",
        )),
        ("replay", (
            "play it again", "play that again", "play this song again", "play the song again",
            "play the same song again", "play my song again",
            "replay the song", "replay song", "replay my song",
            "repeat the song", "repeat song", "repeat my song", "repeat",
        )),
    )
    for media_action, phrases in media_actions:
        if command in phrases:
            return media_control(media_action)

    dictation_result = dictation_command(command, raw_text, voice)
    if dictation_result is not None:
        return dictation_result

    volume_result = volume_command(command)
    if volume_result is not None:
        return volume_result

    brightness_result = brightness_command(command)
    if brightness_result is not None:
        return brightness_result

    if command in (
        "battery", "battery status", "check battery", "check the battery",
        "battery level", "how much battery", "how much battery do i have",
        "is the battery low", "is my battery low", "battery health",
        "check battery status", "how is the battery",
    ):
        return check_battery_status()

    if command in (
        "cpu", "cpu usage", "check cpu", "ram", "ram usage", "check ram",
        "memory usage", "check memory", "system performance", "performance",
        "performance status", "system status", "how is the system",
        "check performance", "cpu and ram", "cpu and memory", "system health",
        "check system health",
    ):
        return check_cpu_ram_usage()

    if command in (
        "check email", "check my email", "check emails", "check my emails",
        "unread emails", "unread email", "check unread emails", "check unread email",
        "how many unread emails", "how many unread emails do i have",
        "any new emails", "any new mail", "check my inbox", "check inbox",
        "check outlook", "check my outlook",
    ):
        return check_unread_emails()

    if command in (
        "show my unread msgs in teams", "show my unread messages in teams",
        "show unread messages in teams", "show my unread msgs in microsoft teams",
        "show my unread messages in microsoft teams", "show unread in teams",
        "open my unread messages in teams", "open my unread chats in teams",
        "open the unread chat in teams", "open unread chat in teams",
        "unread messages in teams", "unread msgs in teams", "unread in teams",
        "teams unread messages", "teams unread msgs", "teams messages",
        "check my teams messages", "check teams messages", "check my teams",
        "check teams", "how many unread messages in teams",
        "how many unread msgs in teams", "read my teams messages",
        "show my teams unread", "my unread messages in teams",
    ):
        return check_teams_unread(open_chat=True)

    if command in (
        "answer the call", "answer call", "accept the call", "accept call",
        "pick up the call", "pick the call", "pick up", "pick up phone",
        "receive the call", "receive call", "take the call", "take call",
        "attend the call", "attend call",
    ):
        return control_phone_call("answer")

    if command in (
        "decline the call", "decline call", "reject the call", "reject call",
        "deny the call", "decline", "reject",
    ):
        return control_phone_call("decline")

    if command in (
        "hang up", "hangup", "end the call", "end call", "end the phone call",
        "disconnect the call", "cut the call", "cut call",
    ):
        return control_phone_call("end")

    if command in (
        "what am i doing", "what am i working on", "what app am i using",
        "which app is open", "what app is open", "current app", "active window",
        "current window", "what window is open", "which window is open",
        "what is on my screen", "what's on my screen",
    ):
        return get_current_active_window()

    news_result = open_news_in_browser(original_command, voice)
    if news_result is not None:
        return news_result

    weather_result = open_weather_in_browser(original_command, voice)
    if weather_result is not None:
        return weather_result

    if command in (
        "read whatsapp",
        "read whatsapp messages",
        "read my whatsapp",
        "read my whatsapp messages",
        "read messages",
        "read my messages",
        "check whatsapp",
        "check my whatsapp",
        "check my whatsapp messages",
    ):
        return read_whatsapp_messages()

    search_result = open_search_in_browser(original_command, voice)
    if search_result is not None:
        return search_result

    url_result = open_url_in_browser(original_command, voice)
    if url_result is not None:
        return url_result

    close_result = close_command(command)
    if close_result is not None:
        return close_result

    app_name = None
    if command in ("claude", "cloud"):
        app_name = "claude"
    else:
        for prefix in ("open ", "launch ", "start "):
            if command.startswith(prefix):
                app_name = command[len(prefix):].strip()
                break

    if app_name:
        return open_application(app_name)

    direct_app = open_application(command)
    if direct_app["ok"]:
        return direct_app
    return {
        "ok": False,
        "message": "Command not recognized. Try saying open or close, followed by an app name.",
    }


class LunarController:
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {
            "status": "ready",
            "message": "Ready for a command",
            "heard": "",
            "speech_text": "",
            "revision": 0,
            "ok": True,
            "microphone_available": sr is not None and sd is not None,
            "wake_enabled": False,
            "wake_stopping": False,
            "incoming_call": False,
            "dictation_enabled": False,
            "open_url": None,
        }
        self._recognizer = sr.Recognizer() if sr is not None else None
        self._microphone = SoundDeviceMicrophone() if sr is not None and sd is not None else None
        self._wake_thread = None
        self._wake_stop = None

    def get_state(self):
        with self._lock:
            return dict(self._state)

    def _set_state(self, **updates):
        with self._lock:
            self._state.update(updates)

    def _complete_command(self, text, result):
        with self._lock:
            self._state.update({
                "status": "ready",
                "message": result["message"],
                "heard": text,
                "speech_text": result["message"],
                "revision": self._state["revision"] + 1,
                "ok": result["ok"],
                # Read by the page to open the link in this same browser window.
                "open_url": result.get("url"),
            })

    def start_listening(self):
        with self._lock:
            if self._state["status"] in ("listening", "processing"):
                return False, dict(self._state)
            if self._state["wake_enabled"] or self._state["wake_stopping"]:
                state = dict(self._state)
                state["message"] = "Turn off hands-free mode before using listen"
                return False, state
            if self._microphone is None or self._recognizer is None:
                self._state.update({
                    "status": "error",
                    "message": "Microphone is unavailable",
                    "ok": False,
                })
                return False, dict(self._state)

            self._state.update({
                "status": "listening",
                "message": "Listening for a command",
                "heard": "",
                "ok": True,
            })

        threading.Thread(target=self._listen_once, daemon=True).start()
        return True, self.get_state()

    def start_wake_mode(self):
        with self._lock:
            if self._microphone is None or self._recognizer is None:
                self._state.update({
                    "status": "error",
                    "message": "Microphone is unavailable",
                    "ok": False,
                })
                return False, dict(self._state)
            if self._state["status"] in ("listening", "processing"):
                return False, dict(self._state)
            if self._state["wake_enabled"]:
                return True, dict(self._state)
            if self._state["wake_stopping"] or (self._wake_thread and self._wake_thread.is_alive()):
                state = dict(self._state)
                state["message"] = "Microphone is busy; try again in a moment"
                return False, state

            stop_event = threading.Event()
            self._wake_stop = stop_event
            self._state.update({
                "status": "ready",
                "message": "Say Lunar to begin",
                "heard": "",
                "wake_enabled": True,
                "wake_stopping": False,
                "ok": True,
            })
            self._wake_thread = threading.Thread(
                target=self._wake_loop,
                args=(stop_event,),
                daemon=True,
            )
            wake_thread = self._wake_thread

        wake_thread.start()
        return True, self.get_state()

    def stop_wake_mode(self):
        with self._lock:
            if not self._state["wake_enabled"] and not self._state["wake_stopping"]:
                return True, dict(self._state)

            if self._wake_stop is not None:
                self._wake_stop.set()
            wake_running = self._wake_thread is not None
            self._state.update({
                "wake_enabled": False,
                "wake_stopping": wake_running,
                "ok": True,
            })
            if self._state["status"] not in ("listening", "processing"):
                self._state.update({
                    "status": "ready",
                    "message": "Turning off hands-free mode" if wake_running else "Hands-free mode is off",
                })
            return True, dict(self._state)

    def _wake_loop(self, stop_event):
        armed_until = 0.0
        try:
            with self._microphone as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.4)
                while not stop_event.is_set():
                    capture_started = time.monotonic()
                    try:
                        audio = self._recognizer.listen(
                            source,
                            timeout=1.0,
                            phrase_time_limit=4.0,
                        )
                    except sr.WaitTimeoutError:
                        if armed_until and time.monotonic() > armed_until:
                            armed_until = 0.0
                            self._set_state(status="ready", message="Say Lunar to begin")
                        continue

                    if stop_event.is_set():
                        break

                    self._microphone.pause()
                    try:
                        try:
                            text = self._recognizer.recognize_google(audio, language="en-IN").strip()
                        except sr.UnknownValueError:
                            continue
                        if stop_event.is_set():
                            break

                        wake_match = find_wake_phrase(text)
                        if wake_match:
                            command = text[wake_match.end():].strip(" \t\r\n,.;:!?")
                            if command:
                                self._set_state(status="processing", message="Working on it", heard=text)
                                self._complete_command(text, handle_command(command, voice=True))
                                armed_until = 0.0
                                if stop_event.wait(1.4):
                                    break
                                self._set_state(status="ready", message="Say Lunar to begin")
                            else:
                                self._complete_command(text, {"ok": True, "message": "Yes? I'm listening."})
                                if stop_event.wait(2.0):
                                    break
                                armed_until = time.monotonic() + 7.0
                                self._set_state(status="ready", message="Go ahead with your command")
                        elif armed_until and capture_started <= armed_until:
                            self._set_state(status="processing", message="Working on it", heard=text)
                            self._complete_command(text, handle_command(text, voice=True))
                            armed_until = 0.0
                            if stop_event.wait(1.4):
                                break
                            self._set_state(status="ready", message="Say Lunar to begin")
                        else:
                            spoken = text.lower().strip(" \t\r\n,.;:!?")
                            if spoken in DICTATION_STOP_PHRASES:
                                stop_dictation()
                            elif CONTROLLER.get_state().get("dictation_enabled"):
                                typed = _spoken_punctuation(text)
                                type_text(typed)
                                self._set_state(
                                    status="ready",
                                    message=f'Typed: "{typed}"',
                                    heard=text,
                                    speech_text="",
                                )
                            else:
                                self._set_state(status="ready", message="Wake phrase not detected", heard=text)
                    finally:
                        if not stop_event.is_set():
                            self._microphone.resume()
        except sr.RequestError:
            self._set_state(
                status="error",
                message="Speech service is offline",
                wake_enabled=False,
                ok=False,
            )
        except Exception as error:
            self._set_state(
                status="error",
                message=f"Wake word error: {error}",
                wake_enabled=False,
                ok=False,
            )
        finally:
            with self._lock:
                if self._wake_stop is stop_event:
                    self._wake_thread = None
                    self._wake_stop = None
                    was_stopping = self._state["wake_stopping"]
                    self._state["wake_stopping"] = False
                    if was_stopping and self._state["status"] not in ("error", "listening", "processing"):
                        self._state.update({
                            "status": "ready",
                            "message": "Hands-free mode is off",
                        })


    def _listen_once(self):
        try:
            with self._microphone as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = self._recognizer.listen(source, timeout=6, phrase_time_limit=8)

            text = self._recognizer.recognize_google(audio, language="en-IN").strip()
            self._set_state(status="processing", message="Working on it", heard=text)
            result = handle_command(text, voice=True)
            self._complete_command(text, result)
        except sr.WaitTimeoutError:
            self._set_state(status="ready", message="No voice detected", heard="", ok=False)
        except sr.UnknownValueError:
            self._set_state(status="ready", message="Voice not recognized", heard="", ok=False)
        except sr.RequestError:
            self._set_state(status="error", message="Speech service is offline", heard="", ok=False)
        except Exception as error:
            self._set_state(status="error", message=f"Voice input error: {error}", heard="", ok=False)

    def run_text_command(self, text):
        with self._lock:
            if self._state["status"] in ("listening", "processing"):
                return False, dict(self._state)
            if self._state["wake_enabled"] or self._state["wake_stopping"]:
                state = dict(self._state)
                state["message"] = "Turn off hands-free mode before using typed commands"
                return False, state
            self._state.update({"status": "processing", "message": "Working on it", "heard": str(text)})

        result = handle_command(text)
        self._complete_command(str(text), result)
        return True, self.get_state()


CONTROLLER = LunarController()

SYSTEM_METRICS = {
    "cpu": None,
    "ram": None,
    "ram_used_gb": None,
    "ram_total_gb": None,
    "gpu": None,
    "gpu_name": None,
    "battery_percent": None,
    "battery_charging": None,
    "updated_at": 0,
}
_GPU_STATE = {"nvml_ok": None, "nvml_handle": None, "name_queried": False,
              "slow_probe_at": 0.0}


def _gpu_name():
    """Adapter name via WMI, in-process, instead of another PowerShell launch."""
    try:
        import wmi
        adapter = wmi.WMI().query("SELECT Name FROM Win32_VideoController")[0]
        return str(adapter.Name).strip() or None
    except Exception:
        return None


def _gpu_sample():
    """Sample GPU utilization: NVML where it exists, throttled PowerShell if not."""
    if _GPU_STATE["nvml_ok"] is None:
        try:
            import pynvml
            pynvml.nvmlInit()
            _GPU_STATE["nvml_handle"] = pynvml.nvmlDeviceGetHandleByIndex(0)
            _GPU_STATE["nvml_ok"] = True
        except Exception:
            _GPU_STATE["nvml_ok"] = False

    if _GPU_STATE["nvml_ok"]:
        try:
            import pynvml
            rates = pynvml.nvmlDeviceGetUtilizationRates(_GPU_STATE["nvml_handle"])
            if not _GPU_STATE["name_queried"]:
                raw = pynvml.nvmlDeviceGetName(_GPU_STATE["nvml_handle"])
                SYSTEM_METRICS["gpu_name"] = raw.decode() if isinstance(raw, bytes) else str(raw)
                _GPU_STATE["name_queried"] = True
            return int(rates.gpu)
        except Exception:
            _GPU_STATE["nvml_ok"] = False

    if not _GPU_STATE["name_queried"]:
        SYSTEM_METRICS["gpu_name"] = _gpu_name()
        _GPU_STATE["name_queried"] = True

    # Without NVML this costs about a second, because it launches PowerShell. A
    # gauge does not need a reading every two seconds, so it is throttled hard.
    now = time.monotonic()
    if now - _GPU_STATE["slow_probe_at"] < 30:
        return SYSTEM_METRICS.get("gpu")
    _GPU_STATE["slow_probe_at"] = now
    try:
        command = (
            "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine "
            "-ErrorAction Stop | Where-Object { $_.Name -like '*engtype_3D*' } |"
            "Measure-Object -Property UtilizationPercentage -Sum | "
            "ForEach-Object { [int][Math]::Round($_.Sum) }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        )
        return min(100, max(0, int(result.stdout.strip() or 0)))
    except Exception:
        return None


def _metrics_loop():
    """Background sampler that keeps SYSTEM_METRICS fresh every 2 seconds."""
    try:
        import psutil
    except ImportError:
        print("[metrics] psutil not available - telemetry disabled", flush=True)
        return
    psutil.cpu_percent(interval=None)  # prime the non-blocking counter
    while True:
        try:
            memory = psutil.virtual_memory()
            SYSTEM_METRICS["cpu"] = round(psutil.cpu_percent(interval=None))
            SYSTEM_METRICS["ram"] = round(memory.percent)
            SYSTEM_METRICS["ram_used_gb"] = round((memory.total - memory.available) / (1024 ** 3), 1)
            SYSTEM_METRICS["ram_total_gb"] = round(memory.total / (1024 ** 3), 1)
            battery = psutil.sensors_battery()
            if battery is not None:
                SYSTEM_METRICS["battery_percent"] = round(battery.percent)
                SYSTEM_METRICS["battery_charging"] = bool(battery.power_plugged)
            SYSTEM_METRICS["gpu"] = _gpu_sample()
            SYSTEM_METRICS["updated_at"] = time.time()
        except Exception:
            pass
        time.sleep(2)


threading.Thread(target=_metrics_loop, daemon=True).start()
threading.Thread(target=_incoming_call_watcher, daemon=True).start()


class LunarRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format_string, *args):
        pass

    def _send_json(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == "/api/state":
            state = CONTROLLER.get_state()
            state["metrics"] = dict(SYSTEM_METRICS)
            state["metrics"].update(_CONTROLS_METRICS)
            self._send_json(200, state)
            return

        if SERVE_UI and route in ("/", "/lunar.html", "/jarvis.html"):
            try:
                page = PAGE_PATH.read_bytes()
            except OSError:
                self._send_json(500, {"ok": False, "message": "Lunar UI file is missing"})
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page)
            return

        # The desktop window replaces the page. The API stays up either way, for
        # the WhatsApp Reader extension.
        self._send_json(404, {"ok": False, "message": "Open the Lunar desktop app"})

    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in ("/api/listen", "/api/command", "/api/wake", "/api/whatsapp/snapshot", "/api/exit"):
            self._send_json(404, {"ok": False, "message": "Not found"})
            return

        if route == "/api/exit":
            # Answer first, then tear down from a timer so the browser gets a real
            # 200 before the socket goes away. Never exit from the handler thread.
            self._send_json(200, {"ok": True})
            threading.Timer(0.5, shutdown_app).start()
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            max_content_length = 65536 if route == "/api/whatsapp/snapshot" else 4096
            if content_length > max_content_length:
                self._send_json(413, {"ok": False, "message": "Request too large"})
                return
            data = json.loads(self.rfile.read(content_length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "message": "Invalid request"})
            return

        if route == "/api/whatsapp/snapshot":
            origin = self.headers.get("Origin", "")
            if not origin.startswith("chrome-extension://"):
                self._send_json(403, {"ok": False, "message": "Lunar Reader extension required"})
                return
            try:
                message_count = WHATSAPP_INBOX.update(data)
            except ValueError as error:
                self._send_json(400, {"ok": False, "message": str(error)})
                return
            self._send_json(200, {"ok": True, "message_count": message_count})
            return

        if route == "/api/listen":
            started, state = CONTROLLER.start_listening()
            self._send_json(202 if started else 409, state)
            return

        if route == "/api/wake":
            enabled = data.get("enabled")
            if not isinstance(enabled, bool):
                self._send_json(400, {"ok": False, "message": "Wake mode must be true or false"})
                return
            if enabled:
                started, state = CONTROLLER.start_wake_mode()
                self._send_json(202 if started else 409, state)
            else:
                _, state = CONTROLLER.stop_wake_mode()
                self._send_json(200, state)
            return

        command = data.get("command", "")
        if not isinstance(command, str):
            self._send_json(400, {"ok": False, "message": "Command must be text"})
            return
        started, state = CONTROLLER.run_text_command(command)
        self._send_json(200 if started else 409, state)


# ---------------- Volume & brightness control (pycaw + WMI) ----------------
_CONTROLS_METRICS = {
    "volume": None,
    "volume_muted": None,
    "brightness": None,
}


def _com_init():
    """Initialize COM on the calling thread (needed in worker/HTTP threads)."""
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass


def _audio_endpoint():
    """Return the master volume interface, or None if pycaw fails."""
    _com_init()
    try:
        from pycaw.pycaw import AudioUtilities
        device = AudioUtilities.GetSpeakers()
        endpoint = getattr(device, "EndpointVolume", None)
        if endpoint is not None:
            return endpoint
        # Older pycaw releases expose Activate() instead.
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import IAudioEndpointVolume
        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
    except Exception:
        return None


def get_system_volume():
    """Read master volume (0-100) into cache; returns int or None."""
    volume = _audio_endpoint()
    if volume is None:
        return None
    try:
        level = round(volume.GetMasterVolumeLevelScalar() * 100)
        _CONTROLS_METRICS["volume"] = level
        _CONTROLS_METRICS["volume_muted"] = bool(volume.GetMute())
        return level
    except Exception:
        return None


def set_system_volume(value):
    value = int(max(0, min(100, value)))
    volume = _audio_endpoint()
    if volume is None:
        return None
    try:
        volume.SetMasterVolumeLevelScalar(value / 100.0, None)
        _CONTROLS_METRICS["volume"] = value
        _CONTROLS_METRICS["volume_muted"] = bool(volume.GetMute())
        return value
    except Exception:
        return None


def set_volume_muted(muted):
    volume = _audio_endpoint()
    if volume is None:
        return None
    try:
        volume.SetMute(bool(muted), None)
        _CONTROLS_METRICS["volume_muted"] = bool(muted)
        return bool(muted)
    except Exception:
        return None


def get_screen_brightness():
    """Read current brightness (0-100) via WMI; returns int or None."""
    _com_init()
    try:
        import wmi
        w = wmi.WMI(namespace="root/wmi")
        reading = w.WmiMonitorBrightness()[0]
        level = int(reading.CurrentBrightness)
        _CONTROLS_METRICS["brightness"] = level
        return level
    except Exception:
        return None


def set_screen_brightness(value):
    value = int(max(0, min(100, value)))
    _com_init()
    try:
        import wmi
        w = wmi.WMI(namespace="root/wmi")
        methods = w.WmiMonitorBrightnessMethods()[0]
        methods.WmiSetBrightness(Brightness=value, Timeout=0)
        _CONTROLS_METRICS["brightness"] = value
        return value
    except Exception:
        return None


def _controls_loop():
    """Slow background sampler for volume/brightness readouts (every 5s)."""
    while True:
        get_system_volume()
        get_screen_brightness()
        time.sleep(5)


threading.Thread(target=_controls_loop, daemon=True).start()


def volume_command(command):
    """Handle volume voice phrases; returns result dict or None if not matched."""
    if "volume" not in command and command not in (
        "mute", "unmute", "louder", "quieter", "make it louder", "make it quieter", "silence",
    ):
        return None
    current = get_system_volume()
    percent_match = re.search(r"(\d{1,3})\s*(?:%|percent)", command)

    if command in (
        "volume up", "increase volume", "increase the volume", "raise volume",
        "raise the volume", "turn volume up", "turn the volume up", "louder",
        "make it louder",
    ):
        new_value = set_system_volume((current if current is not None else 50) + 10)
        if new_value is None:
            return {"ok": False, "message": "I couldn't access the system volume."}
        return {"ok": True, "message": f"Volume is now at {new_value} percent."}

    if command in (
        "volume down", "decrease volume", "decrease the volume", "lower volume",
        "lower the volume", "turn volume down", "turn the volume down", "quieter",
        "make it quieter",
    ):
        new_value = set_system_volume((current if current is not None else 50) - 10)
        if new_value is None:
            return {"ok": False, "message": "I couldn't access the system volume."}
        return {"ok": True, "message": f"Volume is now at {new_value} percent."}

    if command in ("mute", "mute volume", "mute the volume", "mute audio", "silence"):
        if set_volume_muted(True) is None:
            return {"ok": False, "message": "I couldn't access the system volume."}
        return {"ok": True, "message": "Volume muted."}

    if command in ("unmute", "unmute volume", "unmute the volume", "unmute audio"):
        if set_volume_muted(False) is None:
            return {"ok": False, "message": "I couldn't access the system volume."}
        return {"ok": True, "message": "Volume unmuted."}

    if command in (
        "volume", "what is the volume", "what's the volume", "volume status",
        "check volume", "check the volume", "how loud is it", "current volume",
    ):
        if current is None:
            return {"ok": False, "message": "I couldn't read the system volume."}
        muted = " (muted)" if _CONTROLS_METRICS.get("volume_muted") else ""
        return {"ok": True, "message": f"Volume is at {current} percent{muted}."}

    if command.startswith(("set volume", "change volume", "volume to", "make volume")) or (
        "volume" in command and percent_match
    ):
        if not percent_match:
            return {"ok": False, "message": "Tell me a percentage, like set volume to 40 percent."}
        target = min(100, max(0, int(percent_match.group(1))))
        new_value = set_system_volume(target)
        if new_value is None:
            return {"ok": False, "message": "I couldn't access the system volume."}
        return {"ok": True, "message": f"Volume set to {new_value} percent."}

    return None


def brightness_command(command):
    """Handle brightness voice phrases; returns result dict or None if not matched."""
    if "brightness" not in command and command not in (
        "brighter", "dimmer", "make it brighter", "make it dimmer", "dim the screen",
    ):
        return None
    current = get_screen_brightness()
    percent_match = re.search(r"(\d{1,3})\s*(?:%|percent)", command)

    if command in (
        "brightness up", "increase brightness", "increase the brightness",
        "raise brightness", "raise the brightness", "turn brightness up",
        "turn the brightness up", "brighter", "make it brighter",
    ):
        new_value = set_screen_brightness((current if current is not None else 50) + 10)
        if new_value is None:
            return {"ok": False, "message": "Brightness control isn't available on this display."}
        return {"ok": True, "message": f"Brightness is now at {new_value} percent."}

    if command in (
        "brightness down", "decrease brightness", "decrease the brightness",
        "lower brightness", "lower the brightness", "turn brightness down",
        "turn the brightness down", "dimmer", "dim the screen", "make it dimmer",
    ):
        new_value = set_screen_brightness((current if current is not None else 50) - 10)
        if new_value is None:
            return {"ok": False, "message": "Brightness control isn't available on this display."}
        return {"ok": True, "message": f"Brightness is now at {new_value} percent."}

    if command in (
        "brightness", "what is the brightness", "what's the brightness",
        "brightness status", "check brightness", "check the brightness",
        "current brightness", "how bright is the screen",
    ):
        if current is None:
            return {"ok": False, "message": "I couldn't read the screen brightness."}
        return {"ok": True, "message": f"Brightness is at {current} percent."}

    if command.startswith(("set brightness", "change brightness", "brightness to", "make brightness")) or (
        "brightness" in command and percent_match
    ):
        if not percent_match:
            return {"ok": False, "message": "Tell me a percentage, like set brightness to 60 percent."}
        target = min(100, max(0, int(percent_match.group(1))))
        new_value = set_screen_brightness(target)
        if new_value is None:
            return {"ok": False, "message": "Brightness control isn't available on this display."}
        return {"ok": True, "message": f"Brightness set to {new_value} percent."}

    return None


# ---------------- Desktop shortcut & shutdown ----------------
_SERVER = None
_SHUTDOWN_REQUESTED = threading.Event()


def _desktop_folder():
    """Resolve the real Desktop folder, honouring OneDrive redirection."""
    from win32com.shell import shell, shellcon
    return shell.SHGetKnownFolderPath(shellcon.FOLDERID_Desktop)


def create_desktop_shortcut():
    """Point a Desktop shortcut at the running exe. Packaged builds only."""
    if not getattr(sys, "frozen", False):
        return
    try:
        import pythoncom
        import win32com.client

        try:
            desktop = _desktop_folder()
        except Exception:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        os.makedirs(desktop, exist_ok=True)
        link_path = os.path.join(desktop, "Lunar.lnk")

        pythoncom.CoInitialize()
        try:
            script_shell = win32com.client.Dispatch("WScript.Shell")
            link = script_shell.CreateShortCut(link_path)
            # In a onefile build sys.executable is Lunar.exe itself, not the
            # temporary _MEI extraction folder, so the shortcut survives restarts.
            link.TargetPath = sys.executable
            link.WorkingDirectory = os.path.dirname(sys.executable)
            link.IconLocation = f"{sys.executable},0"
            link.Description = "Lunar assistant"
            link.Save()
        finally:
            pythoncom.CoUninitialize()
        print(f"[startup] Desktop shortcut ready: {link_path}", flush=True)
    except Exception as error:
        # A shortcut failure must never stop Lunar from starting.
        print(f"[startup] Desktop shortcut skipped: {error}", flush=True)


def _release_audio():
    """Unmute if Lunar left the system muted, so exit never strands the user."""
    try:
        if _CONTROLS_METRICS.get("volume_muted"):
            _com_init()
            set_volume_muted(False)
            print("[exit] restored system audio", flush=True)
    except Exception as error:
        print(f"[exit] audio cleanup skipped: {error}", flush=True)


def shutdown_app():
    """Stop serving and let the process exit cleanly. Runs off the request thread."""
    if _SHUTDOWN_REQUESTED.is_set():
        return
    _SHUTDOWN_REQUESTED.set()
    # Cleanup must run BEFORE the server stops. Shutting the server down unblocks
    # serve_forever(), the main thread then calls sys.exit(0), and this Timer
    # thread is a daemon thread that would be killed mid-cleanup.
    _release_audio()
    server = _SERVER
    if server is not None:
        try:
            server.shutdown()
        except Exception as error:
            print(f"[exit] server shutdown error: {error}", flush=True)
    print("[exit] Lunar stopped", flush=True)


_INSTANCE_MUTEX = None


def _acquire_single_instance():
    """Hold a named mutex so only one Lunar runs at a time.

    Two copies would double the memory use and fight over the microphone, so a
    second launch just tells the user and quits.
    """
    global _INSTANCE_MUTEX
    try:
        # use_last_error captures the status right after the call; anything
        # ctypes does in between would otherwise overwrite the thread's value.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        handle = kernel32.CreateMutexW(None, False, "Local\\LunarAssistant")
        if not handle:
            return True                      # could not check; let Lunar run
        if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        _INSTANCE_MUTEX = handle             # held for the life of the process
        return True
    except Exception:
        return True


def _serve_loop(server):
    """Serve the local API for as long as the interface is open.

    The WhatsApp Reader extension posts to /api/whatsapp/snapshot, so the server
    runs in-process beside whichever interface is showing rather than as a
    separate app.
    """
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f"[server] stopped: {error}", flush=True)


def _notify_ui():
    """The desktop shell, or None in a build that does not ship it."""
    try:
        import lunar_ui
        return lunar_ui
    except ImportError:
        return None


def _notify(ui, title, message, kind="error"):
    """Report a startup problem. The windowed build has no console to print to."""
    if ui is None:
        print(f"[{title}] {message}", flush=True)
    else:
        ui.notify_error(title, message, kind=kind)


def _start_backend(interface, ui):
    """Take the single-instance lock and start the shared local server.

    Returns (server, exit_code). A None server means Lunar should just quit:
    exit_code 0 if another copy already owns the assistant, 1 if startup failed.
    """
    global _SERVER, SERVE_UI

    if not _acquire_single_instance():
        _notify(ui, "Lunar is already running",
                "Another copy of Lunar is already open.\n\nLook for it on your taskbar, "
                "or check the system tray.", kind="info")
        return None, 0

    try:
        server = ThreadingHTTPServer((HOST, PORT), LunarRequestHandler)
    except OSError as error:
        print(f"[server] port {PORT} unavailable: {error}", flush=True)
        _notify(ui, "Lunar could not start",
                f"Port {PORT} is already in use, so another copy of Lunar is probably "
                f"still running.\n\nClose it, then open Lunar again.")
        return None, 1

    server.daemon_threads = True
    _SERVER = server
    SERVE_UI = interface == UI_WEB
    threading.Thread(target=_serve_loop, args=(server,), daemon=True).start()
    return server, None


def _finish(server):
    """Stop the server and release everything the shutdown path owns."""
    shutdown_app()
    try:
        server.server_close()
    except Exception:
        pass


def main():
    """Desktop interface: Lunar in its own native window."""
    ui = _notify_ui()
    if ui is None:
        print("[ui] lunar_ui.py is missing next to main.py", flush=True)
        return 1

    server, exit_code = _start_backend(UI_DESKTOP, ui)
    if server is None:
        return exit_code

    create_desktop_shortcut()
    try:
        ui.run_desktop(sys.modules[__name__])
    finally:
        _finish(server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
