"""
app_factory — builds the single Flask app that replaces the old split
between a customtkinter desktop app and a separate Flask portal. "/" and
"/content"/"/tiles"/"/chat" are the public LAN-facing student portal;
"/admin" is the password-gated setup/management UI.
"""

import os
import secrets
import sys

from flask import Flask, redirect, request, url_for

from core.downloader import Downloader
from core.hotspot import HotspotManager
from core.jobs import JobTracker
from core.module_manager import ModuleManager
from core.registry import ContentRegistry
from core.tileserver import TileServer
from core.version import get_version

# Resolve asset path whether running from source or frozen (Nuitka)
if getattr(sys, "frozen", False):
    _APP_ROOT = os.path.dirname(sys.executable)
else:
    _APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_TEMPLATE_DIR = os.path.join(_APP_ROOT, "templates")
_ASSETS_DIR = os.path.join(_APP_ROOT, "assets", "portal")

_SETUP_OPEN_PREFIXES = ("/admin/setup", "/admin/downloads", "/admin/login", "/static")


def create_app(config: dict, save_config) -> Flask:
    app = Flask(
        __name__,
        template_folder=_TEMPLATE_DIR,
        static_folder=_ASSETS_DIR,
        static_url_path="/static",
    )

    if not config.get("secret_key"):
        config["secret_key"] = secrets.token_hex(32)
        save_config(config)
    app.secret_key = config["secret_key"]
    app.config["MAX_CONTENT_LENGTH"] = None  # ZIM/model uploads can be multi-GB

    registry = ContentRegistry()
    module_mgr = ModuleManager(registry)
    downloader = Downloader()
    hotspot_mgr = HotspotManager(config)
    tile_server = TileServer()

    app.config.update(
        APP_CONFIG=config,
        SAVE_CONFIG=save_config,
        REGISTRY=registry,
        MODULE_MGR=module_mgr,
        DOWNLOADER=downloader,
        JOBS=JobTracker(),
        HOTSPOT_MGR=hotspot_mgr,
        TILE_SERVER=tile_server,
    )

    from core.blueprints.admin import bp as admin_bp
    from core.blueprints.portal import bp as portal_bp

    app.register_blueprint(portal_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.context_processor
    def _inject_version():
        # Every template, portal and admin alike, can use {{ app_version }}
        # without each route remembering to pass it — single source of truth
        # is the VERSION file (core/version.py), not something re-typed here.
        return {"app_version": get_version()}

    @app.before_request
    def _first_run_gate():
        if config.get("first_run", True):
            if request.path.startswith(_SETUP_OPEN_PREFIXES):
                return None
            return redirect(url_for("admin.setup"))
        return None

    # Re-open any already-installed modules so the admin UI shows correct
    # status immediately, rather than waiting for a student's first request.
    for folder, data in module_mgr.list_modules():
        try:
            module_mgr.open_module(folder, data)
        except Exception:
            pass  # already recorded as an error in the registry

    return app
