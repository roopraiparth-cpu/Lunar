<div align="center">

# LUNAR

*Your personal JARVIS — a voice-driven AI assistant for Windows.*

[![Platform](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-informational)](https://www.python.org/)
[![Desktop Release](https://img.shields.io/badge/desktop_release-v1.0-blue)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![Web Release](https://img.shields.io/badge/web_release-v1.0-red)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**[Download](https://github.com/roopraiparth-cpu/Lunar/releases) · [Commands](#commands) · [Features](#features) · [Why it's light](#why-its-light)**

| ![Lunar dashboard](https://github.com/user-attachments/assets/b394b95f-c290-47b6-b9ad-d56d7b37a140) | ![Lunar interface](https://github.com/user-attachments/assets/84a0ba57-cd0e-4228-a6ad-632b7b341503) | ![Lunar in action](https://github.com/user-attachments/assets/435983f3-bf30-4f5f-a054-60d4d37f8abe) |
|---|---|---|

</div>

---

## About

Lunar is a local AI assistant inspired by JARVIS. Talk to your PC and it
responds — reporting system health, controlling volume and brightness, and
running commands.

It ships in two editions, both powered by the same local engine:

| | Desktop | Web |
|---|---|---|
| **Executable** | `Lunar.exe` | `LunarWeb.exe` |
| **Interface** | Native window (Tkinter/GDI) | Your browser |
| **Entry point** | `main.py` | `web.py` |

<p align="center"><img src="https://github.com/user-attachments/assets/2f804a33-9550-4186-814c-c5096e2dda97" alt="Lunar desktop app" width="238"/></p>

Everything runs on your machine. No cloud dependency, no data leaving your PC.

> **Note:** the Web edition (v1.0) will be retired on **30 October 2026**. It
> will remain downloadable but will not receive new features. New development
> continues in the Desktop edition.

## Getting Started

1. Download from the [Releases](https://github.com/roopraiparth-cpu/Lunar/releases) page
2. Run **Lunar.exe** (desktop) or **LunarWeb.exe** (browser) — a desktop shortcut is created automatically
3. Start talking

> On first launch, Windows SmartScreen may warn about unsigned apps. Click
> **More info → Run anyway**.

Run one edition at a time — they share a server, a port, and the microphone.

## Commands

| Say this…          | Lunar does…                          |
|--------------------|--------------------------------------|
| "check battery"    | Reports battery % and charging state |
| "volume up / down" | Adjusts system volume                |
| "mute / unmute"    | Toggles audio                        |

The window also shows live CPU, RAM, GPU, battery, volume, and brightness —
each with quick controls you can click without saying a word.

## Features

- Voice interaction with natural spoken commands
- Hands-free wake mode ("Lunar …") and dictation
- Live system telemetry — CPU, RAM, GPU, battery, volume, brightness
- Audio and brightness control by voice or by click
- Native desktop window — no browser engine required
- Spoken replies through Windows SAPI, with selectable voice and speed
- Zero-setup installation with automatic desktop shortcut

## Why it's light

The desktop app is a plain Tkinter window drawn with GDI — no browser engine,
no GPU compositing, no web fonts:

- **~71 MB** RAM, single process
- **~0.8%** of one CPU core when idle — the interface only redraws while Lunar
  is listening, working, or speaking
- **No GPU usage** beyond reading the utilisation counter

The Web edition costs the same on Lunar's side; whatever the browser itself
uses is on the browser.

## For Developers

```bash
git clone https://github.com/roopraiparth-cpu/Lunar.git
cd Lunar
pip install -r requirements.txt

python main.py     # desktop window
python web.py      # browser interface
```

Point Lunar at your own portal with an environment variable before starting:

```bat
set LUNAR_HOMEWORK_URL=https://your-school.example/feed
```

| File | Role |
|------|------|
| `main.py`     | Command handling, system integration, the local API server |
| `lunar_ui.py` | The native desktop window |
| `web.py`      | Web entry point: serves `lunar.html`, opens the browser |
| `lunar.html`  | The browser interface, used only by `LunarWeb.exe` |

Both executables build from the repo with `pyinstaller Lunar.spec` and
`pyinstaller LunarWeb.spec`.
