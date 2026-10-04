
<div align="center">

### MOONFALL LABS

# LUNAR

*Your personal JARVIS — a voice-driven AI assistant for Windows, in your browser.*

[![Platform](https://img.shields.io/badge/platform-Windows-blue)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![Python](https://img.shields.io/badge/python-3.12%2B-informational)](https://www.python.org/)
[![Release](https://img.shields.io/badge/release-v1.0-blue)](https://github.com/roopraiparth-cpu/Lunar/releases)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**[Download](https://github.com/roopraiparth-cpu/Lunar/releases) · [Commands](#commands) · [Features](#features) · [Support](#support)**

| ![Lunar dashboard](https://github.com/user-attachments/assets/b394b95f-c290-47b6-b9ad-d56d7b37a140) | ![Lunar interface](https://github.com/user-attachments/assets/84a0ba57-cd0e-4228-a6ad-632b7b341503) | ![Lunar in action](https://github.com/user-attachments/assets/435983f3-bf30-4f5f-a054-60d4d37f8abe) |
|---|---|---|

</div>

---

## About

Lunar is a local AI assistant inspired by JARVIS. Talk to your PC and it
responds — reporting system health, controlling volume and brightness, and
running commands through a clean interface in your browser.

One lightweight executable serves the interface locally and opens it in your
default browser. The system-control engine runs entirely on your machine —
no cloud dependency, no data leaving your PC.

## Getting Started

1. Download `LunarWeb.exe` from the [Releases](https://github.com/roopraiparth-cpu/Lunar/releases) page
2. Run it — the Lunar interface opens in your browser
3. Start talking

No Python required — everything is bundled inside the executable.

> On first launch, Windows SmartScreen may warn about unsigned apps. Only
> continue if you downloaded Lunar from this repository.

## Commands

| Say this… | Lunar does… |
|---|---|
| "check battery" | Reports the battery level and charging state |
| "volume up" / "volume down" | Adjusts system volume |
| "mute" / "unmute" | Changes the audio mute state |
| "homework" | Opens the configured school portal |

The interface also shows live CPU, RAM, GPU, battery, volume, and brightness —
each with quick controls you can click without speaking.

## Features

- Voice commands, hands-free wake mode ("Lunar …"), and dictation
- Live system telemetry: CPU, RAM, GPU, battery, volume, and brightness
- Volume and brightness control by voice or by click
- Local web interface — served on your machine, opened in your browser
- Spoken replies using Windows SAPI, with selectable voice and speed
- Zero-setup installation — one executable, no dependencies

## For Developers

```bash
git clone https://github.com/roopraiparth-cpu/Lunar.git
cd Lunar
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python web.py      # run from source
```

To configure the portal opened by the `homework` command, set
`LUNAR_HOMEWORK_URL` before starting Lunar:

```bat
set LUNAR_HOMEWORK_URL=https://your-school.example/feed
python web.py
```

| File | Role |
|---|---|
| `web.py` | Entry point: serves the local API and `lunar.html`, opens the browser |
| `lunar.html` | The Lunar interface |
| `main.py` | Shared command handling and system integration |

Build the executable with the included PyInstaller spec:

```bash
pyinstaller LunarWeb.spec
```

## Support

Found a bug or have a feature request? Please open a
[GitHub issue](https://github.com/roopraiparth-cpu/Lunar/issues) — it helps
everyone.

For anything else, email [roopraiparth900@gmail.com](mailto:roopraiparth900@gmail.com).

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Lunar** is built and maintained by **Moonfall Labs**.

[Releases](https://github.com/roopraiparth-cpu/Lunar/releases) · [Issues](https://github.com/roopraiparth-cpu/Lunar/issues) · [Email support](mailto:roopraiparth900@gmail.com)

© 2026 Moonfall Labs · Distributed under the [MIT License](LICENSE)

</div>

