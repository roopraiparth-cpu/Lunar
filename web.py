"""Web interface for Lunar.

The entry point for Lunar: it serves lunar.html and opens your browser, and
builds as LunarWeb.exe. The assistant itself lives in main.py.

Only one Lunar can run at a time - one server, one port, one microphone - so a
second launch tells you and quits.
"""

import os
import sys
import threading
import time
import urllib.request
import webbrowser

# Aliased because this module has its own main() below.
import main as lunar


def _open_browser(url):
    """Open the page in the default browser once the server is answering."""
    for _ in range(40):
        try:
            with urllib.request.urlopen(url, timeout=1):
                break
        except Exception:
            time.sleep(0.25)
    webbrowser.open_new(url)


def main():
    server, exit_code = lunar._start_backend()
    if server is None:
        return exit_code

    if os.environ.get("LUNAR_NO_BROWSER") != "1":
        url = f"http://{lunar.HOST}:{lunar.PORT}/"
        threading.Timer(0.7, _open_browser, args=(url,)).start()

    try:
        # The page's Exit button posts /api/exit, which sets this event.
        lunar._SHUTDOWN_REQUESTED.wait()
    except KeyboardInterrupt:
        print("[exit] interrupted", flush=True)
    finally:
        lunar._finish(server)
    return 0


if __name__ == "__main__":
    sys.exit(main())