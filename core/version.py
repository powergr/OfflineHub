"""
version: single source of truth for the app version.

Reads the VERSION file at the app root (bundled next to OfflineHub.exe in
frozen builds via build.bat's --include-data-files) so build.bat,
installer.iss, main.py, and the Settings page never drift out of sync with
each other.
"""

import os
import sys


def _app_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_version() -> str:
    path = os.path.join(_app_root(), "VERSION")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "0.0.0-unknown"


__version__ = get_version()
