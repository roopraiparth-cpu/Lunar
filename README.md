<div align="center">

# LUNAR

*Your personal JARVIS — A voice-driven AI assistant for Windows.*

[![Platform](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-informational)](https://www.python.org/)
[![Release](https://img.shields.io/badge/Web_Releases-Lunar_Web_V_1.0-red)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![Release](https://img.shields.io/badge/Desktop_Releases-Lunar_Desktop_V_1.0-blue)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**[Download](https://github.com/roopraiparth-cpu/Lunar/releases) · [Commands](#commands) · [Features](#features) · [Why it's light](#why-its-light)**

*Note - Web Release will not be operatable after 30th October, 2026 , but will be available for download, but the New features would not be accessible*

</div>

---

## About

Lunar is a local AI assistant inspired by JARVIS. Talk to your PC and it
responds — reporting system health, controlling volume, and running commands.

It ships in two flavours, both talking to the same local engine:

| App            | Entry point | What you get                            |
|----------------|-------------|-----------------------------------------|
| **Lunar.exe**  | `main.py`   | A native desktop window (Tkinter/GDI)   |
| **LunarWeb.exe** | `web.py`   | The classic interface, in your browser  |

Everything runs on your machine. No cloud dependency, no data leaving your PC.

## Getting Started

1. Download from the [Releases](https://github.com/roopraiparth-cpu/Lunar/releases) page
2. Run **Lunar.exe** for the desktop app — a desktop shortcut is created automatically
   — or **LunarWeb.exe** for the browser version
3. Start talking

> On first launch, Windows SmartScreen may show a warning for unsigned apps.
> Click **More info → Run anyway**.

Only one of the two runs at a time. They share a server, a port, and a
microphone, so starting the second while the first is open simply tells you so.

## Commands

| Say this…          | Lunar does…                          |
|--------------------|--------------------------------------|
| "check battery"    | Reports battery % and charging state |
| "volume up / down" | Adjusts system volume                |
| "mute / unmute"    | Toggles audio                        |

The window also shows live CPU, RAM, GPU, battery, volume, and brightness —
each with quick stepper buttons you can click without saying anything.

## Features

- Voice interaction with natural spoken commands
- Hands-free wake mode ("Lunar …") and hands-free dictation
- Live system telemetry — CPU, RAM, GPU, battery, volume, brightness
- Audio and screen brightness control by voice or by click
- Native desktop window — no browser, no embedded web engine
- Spoken replies through Windows SAPI, with a selectable voice and speed
- Zero-setup installation with automatic desktop shortcut

## Why it's light

The desktop app is a plain Tkinter window drawn with GDI, so it needs no browser
engine, no GPU compositing, and no web fonts:

- **~71 MB** of RAM while running, in a single process
- **~0.8%** of one CPU core when idle; the arc core only redraws while Lunar is
  listening, working, or speaking
- **No GPU usage** beyond reading the utilisation counter
- A still window costs nothing — widgets update only when a value changes

The browser version costs the same on Lunar's side; whatever the browser itself
uses is on the browser.

## For Developers

```bash
git clone https://github.com/roopraiparth-cpu/Lunar.git
cd Lunar
pip install -r requirements.txt

python main.py     # desktop window
python web.py      # browser interface
```

Say **"homework"** to open your school portal. Point Lunar at your own portal
with an environment variable, set before starting it:

```bat
set LUNAR_HOMEWORK_URL=https://your-school.example/feed
```

| File | Role |
|------|------|
| `main.py`     | Command handling, system integration, the local API server |
| `lunar_ui.py` | The native desktop window |
| `web.py`      | Web entry point: serves `lunar.html`, opens the browser |
| `lunar.html`  | The browser interface, used only by `LunarWeb.exe` |

`main.py` owns the server both entry points share, which is also what the
WhatsApp Reader extension talks to. Build both exes with:

```bash
pyinstaller Lunar.spec
pyinstaller LunarWeb.spec
```
