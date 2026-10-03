<div align="center">

### MOONFALL LABS

# LUNAR

*Your personal JARVIS — a voice-driven AI assistant for Windows.*

[![Platform](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-informational)](https://www.python.org/)
[![Desktop Release](https://img.shields.io/badge/desktop-v1.0-blue)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![Web Release](https://img.shields.io/badge/web-v1.0-red)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**[Download](https://github.com/roopraiparth-cpu/Lunar/releases) · [Commands](#commands) · [Features](#features) · [Support](#support)**

| ![Lunar dashboard](https://github.com/user-attachments/assets/b394b95f-c290-47b6-b9ad-d56d7b37a140) | ![Lunar interface](https://github.com/user-attachments/assets/84a0ba57-cd0e-4228-a6ad-632b7b341503) | ![Lunar in action](https://github.com/user-attachments/assets/435983f3-bf30-4f5f-a054-60d4d37f8abe) |
|---|---|---|

</div>

---

## About

Lunar is a Windows assistant inspired by JARVIS. It helps you check system
status, control volume and brightness, and use voice commands through a
straightforward interface.

Lunar is available in two editions:

| Edition | Download | Interface |
|---|---|---|
| Desktop | `Lunar.exe` | Native Windows window |
| Web | `LunarWeb.exe` | Opens in your browser |

<p align="center">
  <img src="https://github.com/user-attachments/assets/2f804a33-9550-4186-814c-c5096e2dda97" alt="Lunar desktop app" width="238">
</p>

Lunar's system-control engine runs locally on your PC. The Web edition loads
fonts from Google Fonts.

> **Web edition notice:** The Web edition is scheduled to stop operating after
> **30 October 2026**. Its current release will remain available to download,
> but it will not receive new features. New development will focus on the
> Desktop edition.

## Getting Started

1. Visit the [Releases](https://github.com/roopraiparth-cpu/Lunar/releases) page.
2. Download and run `Lunar.exe` for the Desktop edition or `LunarWeb.exe` for
   the Web edition. Python is not required to run either packaged app.
3. Start using Lunar.

On first launch, Windows SmartScreen may warn that the app is unsigned. Only
continue if you downloaded Lunar from this repository.

Run one edition at a time. They share a server, a port, and the microphone.

## Commands

| Say this… | Lunar does… |
|---|---|
| “check battery” | Reports the battery level and charging state |
| “volume up” or “volume down” | Adjusts system volume |
| “mute” or “unmute” | Changes the audio mute state |
| “homework” | Opens the configured school portal |

The interface also shows live CPU, RAM, GPU, battery, volume, and brightness
information. You can use its controls without speaking.

## Features

- Voice commands, wake mode, and dictation
- Live system information: CPU, RAM, GPU, battery, volume, and brightness
- Volume and brightness controls by voice or through the interface
- Native Desktop edition built with Tkinter and GDI
- Spoken replies using Windows SAPI, with voice and speed options
- Automatic Desktop shortcut for the Desktop edition

## Why it's light

Approximate measurements for the Desktop edition:

- **About 71 MB of RAM**
- **About 0.8% CPU while idle**; usage varies by hardware and activity
- **No GPU rendering**; Lunar reads the GPU utilisation counter for system
  information

The Web edition's browser may use additional system resources.

## For Developers

```bash
git clone https://github.com/roopraiparth-cpu/Lunar.git
cd Lunar
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python main.py     # Desktop edition
python web.py      # Web edition
```

To configure the portal opened by the `homework` command, set
`LUNAR_HOMEWORK_URL` in Windows Command Prompt before starting Lunar:

```bat
set LUNAR_HOMEWORK_URL=https://your-school.example/feed
python main.py
```

| File | Role |
|---|---|
| `main.py` | Command handling, system integration, and the local API server |
| `lunar_ui.py` | Native Desktop interface |
| `web.py` | Web entry point; serves `lunar.html` and opens the browser |
| `lunar.html` | Interface used by the Web edition |

Build the executables with the included PyInstaller specifications:

```bash
pyinstaller Lunar.spec
pyinstaller LunarWeb.spec
```

## Support

Found a bug or have a feature request? Please open a
[GitHub issue](https://github.com/roopraiparth-cpu/Lunar/issues).

For other support, email [roopraiparth900@gmail.com](mailto:roopraiparth900@gmail.com).

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Lunar** is built and maintained by **Moonfall Labs**.

© 2026 Moonfall Labs · Distributed under the [MIT License](LICENSE)

</div>
