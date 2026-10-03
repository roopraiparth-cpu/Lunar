# Lunar WhatsApp Reader

This read-only Chrome extension shares text from the currently open WhatsApp Web chat with Lunar at 127.0.0.1 while that browser tab is visible. It keeps the latest snapshot in Lunar memory for up to five minutes. It does not send WhatsApp messages or save chat text to disk.

## Install in Chrome

1. Start Lunar from the project folder with .\.venv\Scripts\python.exe .\main.py.
2. Open chrome://extensions in Chrome and turn on Developer mode.
3. Choose Load unpacked and select the whatsapp_extension folder.
4. Open or refresh https://web.whatsapp.com/ and link your account if asked.
5. Leave the chat you want to read open and keep that tab visible.
6. In Lunar, say or type read WhatsApp messages.

The small LUNAR LINK badge on WhatsApp Web shows whether the local bridge is connected. This extension only reads text currently present in the open chat; images, audio, and other attachments are skipped.
