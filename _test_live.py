"""Real-execution test: runs Lunar's read-only commands for real, unstubbed.

These handlers only *read* from Windows (battery, CPU/RAM, active window), so
running them for real is safe and is the only way to know the underlying
pywin32/psutil calls still work after the desktop removal.

Run:  .venv/Scripts/python.exe _test_live.py
"""
import sys

import main

# Read-only only. Nothing here launches, closes, or changes anything.
LIVE = [
    "hello",
    "how are you",
    "check battery",
    "system health",
    "what am i doing",
    "weather in London",
    "news about the election",
    "play music",          # stubbed below - media keys are a side effect
]

# Media keys, app launching and calls genuinely change machine state, so those
# stay stubbed. This file only exercises the read-only handlers for real.
main.media_control = lambda a: {"ok": True, "message": f"[stub] media_control:{a}"}
main.open_last_song = lambda: {"ok": True, "message": "[stub] open_last_song"}

failures = 0
for phrase in LIVE:
    try:
        result = main.handle_command(phrase, voice=False)
    except Exception as exc:
        print(f"  RAISED   {phrase!r}: {exc!r}")
        failures += 1
        continue
    if not isinstance(result, dict) or "ok" not in result:
        print(f"  MALFORMED {phrase!r}: {result!r}")
        failures += 1
        continue
    msg = str(result["message"])
    flag = "ok " if result["ok"] else "err"
    # A command can legitimately report ok=False (no battery, Outlook absent).
    # What must never happen is an unhandled crash or an empty reply.
    if not msg.strip():
        failures += 1
        msg = "<EMPTY MESSAGE>"
    print(f"  [{flag}] {phrase!r:28} -> {msg[:88]}")

print(f"\n{len(LIVE) - failures}/{len(LIVE)} live commands returned a real result")
sys.exit(1 if failures else 0)