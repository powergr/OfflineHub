"""
Offline Knowledge Hub: Entry Point.

No customtkinter, no GUI event loop. Boots one Flask app (student portal +
admin UI, see core/app_factory.py) and runs it with a system tray icon as
the visible running/quit signal, since there's no window anymore.
"""

import json
import logging
import os
import sys
import threading
import webbrowser

from core.logging_setup import setup_logging
from core.version import get_version

logger = logging.getLogger(__name__)

BASE_DIR    = r"C:\OfflineHub"
MODULES_DIR = os.path.join(BASE_DIR, "modules")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

for d in (BASE_DIR, MODULES_DIR):
    os.makedirs(d, exist_ok=True)

DEFAULT_CONFIG = {
    "first_run": True,
    "version": get_version(),
    "admin_password_hash": "",
    "admin_password_salt": "",
    "secret_key": "",
    "language": "en",
    "hotspot": {
        "ssid": "OfflineHub",
        "password": "offlinehub2026",
        "enabled": False,
    },
    "portal_port": 8000,
    "autostart": False,
    "modules": {},
}


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            data.setdefault(k, v)
        data["version"] = get_version()  # always reflect the running build, not a stale value
        return data
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def _icon_path() -> str:
    if getattr(sys, "frozen", False):
        root = os.path.dirname(sys.executable)
    else:
        root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(root, "assets", "icons", "hub.ico")


def _build_tray(config: dict, server, hotspot_mgr, registry):
    import pystray
    from PIL import Image

    image = Image.open(_icon_path())
    base_url = f"http://127.0.0.1:{config.get('portal_port', 8000)}"

    def open_portal(icon, item):
        webbrowser.open(base_url + "/")

    def open_admin(icon, item):
        webbrowser.open(base_url + "/admin")

    def quit_app(icon, item=None):
        logger.info("Quit requested")
        icon.stop()
        try:
            registry.unload_all()
        except Exception:
            logger.exception("Error unloading modules on quit")
        try:
            hotspot_mgr.stop()
        except Exception:
            logger.exception("Error stopping hotspot on quit")
        server.shutdown()

    menu = pystray.Menu(
        pystray.MenuItem("Open Portal", open_portal, default=True),
        pystray.MenuItem("Open Admin", open_admin),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("OfflineHub", image, "Offline Knowledge Hub", menu)
    return icon, quit_app


def main():
    setup_logging()

    from core.single_instance import acquire

    if not acquire():
        logger.warning(
            "Another OfflineHub instance is already running - opening it "
            "instead of starting a second one."
        )
        config = load_config()
        port = config.get("portal_port", 8000)
        webbrowser.open(f"http://127.0.0.1:{port}/")
        return

    logger.info("OfflineHub %s starting", get_version())

    from werkzeug.serving import make_server

    from core.app_factory import create_app

    config = load_config()
    app = create_app(config, save_config)

    if config["hotspot"].get("enabled"):
        threading.Thread(target=app.config["HOTSPOT_MGR"].start, daemon=True).start()

    port = config.get("portal_port", 8000)
    server = make_server("0.0.0.0", port, app, threaded=True)

    tray, quit_app = _build_tray(config, server, app.config["HOTSPOT_MGR"], app.config["REGISTRY"])

    from flask import abort, request

    @app.route("/_internal/quit", methods=["POST"])
    def _internal_quit():
        # Loopback-only. Lets the uninstaller (uninstall_stop_hotspot.ps1)
        # ask the app to shut down the same way the tray's own Quit menu
        # item does, instead of going straight to taskkill /F. This matters
        # because pystray only deletes its own notification-area icon
        # (Shell_NotifyIcon NIM_DELETE) inside that graceful path - a forced
        # kill skips it entirely and leaves a stale, unresponsive tray icon
        # behind until the next Explorer restart. Confirmed live: this is
        # exactly what was happening on every non-graceful exit. Registered
        # before the server thread starts, so there's no route ever added
        # while a request could already be in flight.
        if request.remote_addr not in ("127.0.0.1", "::1"):
            abort(403)
        threading.Thread(target=quit_app, args=(tray,), daemon=True).start()
        return ("", 204)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    landing = "/admin/setup" if config.get("first_run", True) else "/"
    webbrowser.open(f"http://127.0.0.1:{port}{landing}")

    tray.run()  # blocks until Quit is chosen; server_thread is a daemon so process exits with it


if __name__ == "__main__":
    main()
