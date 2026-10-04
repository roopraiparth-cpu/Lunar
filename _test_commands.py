"""Exhaustive command-routing test for Lunar's web build.

Every phrase in every command group is extracted from handle_command's AST and
run through it with all side-effecting leaves stubbed out, so routing is
verified without launching apps, pressing media keys or changing volume.

Run:  .venv/Scripts/python.exe _test_commands.py
"""
import ast
import sys
import traceback

import main

CALLS = []


def _recorder(label, ok=True, extra=None):
    def stub(*args, **kwargs):
        CALLS.append((label, args, kwargs))
        return {"ok": ok, "message": f"[stub] {label}", **(extra or {})}
    return stub


# Side-effecting leaves: stubbed so nothing on the machine actually changes.
# The four *_in_browser matchers are deliberately NOT stubbed - they are
# matchers, not actions, and with voice=False they only hand a URL back for the
# page to open. Stubbing them would make every junk phrase "match" and hide the
# real fall-through behaviour the negative controls are there to catch.
STUBS = {
    "open_application": _recorder("open_application"),
    "open_last_song": _recorder("open_last_song"),
    "media_control": _recorder("media_control"),
    "control_phone_call": _recorder("control_phone_call"),
    "read_whatsapp_messages": _recorder("read_whatsapp_messages"),
    "check_unread_emails": _recorder("check_unread_emails"),
    "check_teams_unread": _recorder("check_teams_unread"),
    "close_active_app": _recorder("close_active_app"),
    "close_application": _recorder("close_application"),
    "get_system_volume": lambda: 50,
    "set_system_volume": lambda v: v,
    "set_volume_muted": lambda m: True,
    "get_screen_brightness": lambda: 60,
    "set_screen_brightness": lambda v: v,
}

ORIGINALS = {}
for name, stub in STUBS.items():
    if not hasattr(main, name):
        print(f"FATAL: main.{name} does not exist - harness is stale")
        sys.exit(2)
    ORIGINALS[name] = getattr(main, name)
    setattr(main, name, stub)


def extract_phrases():
    """Every string literal sitting in a tuple/list inside handle_command."""
    tree = ast.parse(open("main.py", encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "handle_command")
    phrases = set()
    for node in ast.walk(fn):
        if isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    v = elt.value.strip()
                    if v and len(v) < 60:
                        phrases.add(v)
    return sorted(phrases)


def main_test():
    phrases = extract_phrases()
    print(f"extracted {len(phrases)} command phrases from handle_command\n")

    failures, unrecognised, routes = [], [], {}
    for phrase in phrases:
        CALLS.clear()
        try:
            result = main.handle_command(phrase, voice=False)
        except Exception:
            failures.append((phrase, traceback.format_exc().strip().splitlines()[-1]))
            continue
        if not isinstance(result, dict) or "ok" not in result or "message" not in result:
            failures.append((phrase, f"malformed result: {result!r}"))
            continue
        msg = result["message"]
        if "Command not recognized" in msg:
            unrecognised.append((phrase, msg))
        label = CALLS[0][0] if CALLS else "inline"
        routes.setdefault(label, []).append(phrase)

    print("=== routing ===")
    for label in sorted(routes, key=lambda k: -len(routes[k])):
        print(f"  {label:28} {len(routes[label]):>4} phrases")

    print(f"\ntotal phrases : {len(phrases)}")
    print(f"routed        : {len(phrases) - len(unrecognised) - len(failures)}")
    print(f"unrecognised  : {len(unrecognised)}")
    print(f"exceptions    : {len(failures)}")

    if unrecognised:
        print("\n!!! NOT RECOGNISED !!!")
        for phrase, msg in unrecognised[:25]:
            print(f"  {phrase!r} -> {msg}")
    if failures:
        print("\n!!! EXCEPTIONS / MALFORMED !!!")
        for phrase, err in failures[:25]:
            print(f"  {phrase!r} -> {err}")

    # Negative controls: junk must fall through to the "not recognized" reply.
    # These run against the REAL open_application, because fall-through ends
    # there - a stub that accepts everything would hide a genuine regression.
    print("\n=== negative controls ===")
    real_open_application = ORIGINALS["open_application"]
    main.open_application = real_open_application

    # Expectations for "open"/"launch"/"start" changed on purpose: the app now
    # asks which app instead of falling through to the fuzzy resolver, which
    # used to match the bare word "open" to OpenShot and launch it.
    controls = [
        ("", "didn't receive"),
        ("   ", "didn't receive"),
        ("qwertyuiop", "Command not recognized"),
        ("zzzz nonsense zzzz", "Command not recognized"),
        ("the quick brown fox jumps", "Command not recognized"),
        ("open ", "Which app should I open"),
        ("open", "Which app should I open"),
        ("launch ", "Which app should I open"),
        ("launch", "Which app should I open"),
        ("start ", "Which app should I open"),
        ("start", "Which app should I open"),
        ("close ", "Which app should I close"),
    ]
    bad = []
    for text, expected in controls:
        CALLS.clear()
        try:
            res = main.handle_command(text, voice=False)
        except Exception as exc:
            bad.append((text, f"raised {exc!r}"))
            continue
        if expected not in res["message"]:
            bad.append((text, f"expected {expected!r}, got {res['message']!r}"))
    main.open_application = STUBS["open_application"]

    for text, why in bad:
        print(f"  FAIL {text!r} -> {why}")
    print(f"  {len(controls) - len(bad)}/{len(controls)} negative controls correct")

    ok = not failures and not unrecognised and not bad
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main_test())