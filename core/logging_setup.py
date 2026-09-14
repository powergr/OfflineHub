"""
logging_setup — one rotating log file under C:\\OfflineHub\\logs\\.

Today's build (--windows-console-mode=disable, see build.bat) has no
console window at all once launched from the Start Menu or autostart, so a
print() or an unhandled exception previously vanished with nobody able to
see it. setup_logging() attaches both a rotating file handler and a console
handler to the root logger, so any module's logging.getLogger(__name__)
calls - and Werkzeug's own per-request access log, which propagates to the
root logger by default - land in the file too.
"""

import logging
import logging.handlers
import os

LOG_DIR = r"C:\OfflineHub\logs"
LOG_FILE = os.path.join(LOG_DIR, "offlinehub.log")

_configured = False


def setup_logging(level: int = logging.INFO):
    global _configured
    if _configured:
        return
    _configured = True

    os.makedirs(LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
