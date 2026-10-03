<div align="center">

# LUNAR

*Your personal JARVIS — a voice-driven AI assistant for Windows.*

[![Platform](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-informational)](https://www.python.org/)
[![Release](https://img.shields.io/badge/release-v1.0-blue)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**[Download](https://github.com/roopraiparth-cpu/Lunar/releases) · [Commands](#commands) · [Features](#features)**

</div>

---

## About

Lunar is a local AI assistant inspired by JARVIS. Talk to your PC and it
responds — reporting system health, controlling volume, and running commands
through a clean interface in your browser.

Everything runs on your machine. No cloud dependency, no data leaving your PC.

## Getting Started

1. Download **Lunar.exe** from the [Releases](https://github.com/roopraiparth-cpu/Lunar/releases) page
2. Run it — a desktop shortcut is created automatically
3. Lunar opens in your browser. Start talking.

> On first launch, Windows SmartScreen may show a warning for unsigned apps.
> Click **More info → Run anyway**.

## Commands

| Say this…          | Lunar does…                          |
|--------------------|--------------------------------------|
| "check battery"    | Reports battery % and charging state |
| "volume up / down" | Adjusts system volume                |
| "mute / unmute"    | Toggles audio                        |

The dashboard also shows live CPU, RAM, GPU, and battery metrics.

## Features

- Voice interaction with natural spoken commands
- Live system telemetry — CPU, RAM, GPU, battery
- Audio control by voice
- Local web interface, served entirely on your machine
- Zero-setup installation with automatic desktop shortcut

## For Developers

```bash
git clone https://github.com/roopraiparth-cpu/Lunar.git
cd Lunar
pip install -r requirements.txt
python main.py
