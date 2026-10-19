"""Thin wrappers around macOS command line tools. Fall back to stderr elsewhere."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

TITLE = "Проверка синтаксиса"

# Automator runs scripts without a locale, and pbcopy/pbpaste then mangle non-ASCII text.
_UTF8_ENV = dict(os.environ, LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")


def is_macos() -> bool:
    return sys.platform == "darwin"


def _applescript_str(value: str) -> str:
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def notify(message: str, subtitle: str = "") -> None:
    if not is_macos():
        sys.stderr.write("%s%s\n" % (message, " — " + subtitle if subtitle else ""))
        return
    script = "display notification %s with title %s" % (
        _applescript_str(subtitle or message), _applescript_str(TITLE))
    if subtitle:
        script += " subtitle %s" % _applescript_str(message)
    subprocess.run(["osascript", "-e", script], check=False)


def paste() -> str:
    out = subprocess.run(["pbpaste"], capture_output=True, env=_UTF8_ENV, check=True).stdout
    return out.decode("utf-8", errors="replace")


def copy(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=_UTF8_ENV, check=True)


def write_report(html_text: str) -> Path:
    """Write the report to the user's private temp dir, replacing the previous one."""
    folder = Path(tempfile.gettempdir()) / "jinja_json_checker"
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / "report.html"
    path.write_text(html_text, encoding="utf-8")
    return path


def open_file(path: Path) -> None:
    if is_macos():
        subprocess.run(["open", str(path)], check=False)
    else:
        sys.stderr.write("Отчёт: %s\n" % path)
