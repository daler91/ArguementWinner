"""Best-effort desktop notifications — stdlib only, never raises.

Always prints to the console the helper runs in; additionally fires a native
notification when the platform has one available, and silently no-ops when it
doesn't (headless, missing `notify-send`, etc.)."""

from __future__ import annotations

import shutil
import subprocess
import sys

_MAX_BODY = 240


def notify(title: str, body: str = "") -> None:
    line = f"[argumentwinner] {title}"
    print(line if not body else f"{line}\n    {body}", flush=True)
    snippet = body[:_MAX_BODY]
    try:
        if sys.platform == "darwin":
            script = f"display notification {_osa(snippet)} with title {_osa(title)}"
            subprocess.run(
                ["osascript", "-e", script], timeout=3, check=False, capture_output=True
            )
        elif sys.platform.startswith("linux") and shutil.which("notify-send"):
            subprocess.run(
                ["notify-send", title, snippet], timeout=3, check=False, capture_output=True
            )
        # Windows has no dependency-free native toast; the console line stands.
    except Exception:  # noqa: BLE001 — a notification failure must never break the helper
        pass


def _osa(text: str) -> str:
    """Quote a string for an AppleScript literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
