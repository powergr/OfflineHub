"""
PortalServer — serves the browser-facing landing page on the local network.
"""

import os
import sys
import socket
import threading

from flask import Flask, render_template_string, jsonify, send_from_directory
from core.tileserver import TileServer

# Resolve asset path whether running frozen (PyInstaller/Nuitka) or from source
if getattr(sys, "frozen", False):
    if hasattr(sys, "_MEIPASS"):
        # Legacy PyInstaller compatibility
        ASSETS_DIR = os.path.join(sys._MEIPASS, "assets", "portal")
    else:
        # Nuitka compatibility: assets are next to the .exe
        ASSETS_DIR = os.path.join(os.path.dirname(sys.executable), "assets", "portal")
else:
    ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "portal")


class PortalServer:

    def __init__(self, config: dict, service_mgr):
        self.config      = config
        self.service_mgr = service_mgr
        self.app         = Flask(__name__)
        self.tile_server = TileServer()
        self._server     = None
        self._thread     = None

        self._register_routes()

    # ── Routes ────────────────────────────────────────────────────────────────

    def _register_routes(self):
        app = self.app

        @app.route("/")
        def index():
            return send_from_directory(ASSETS_DIR, "index.html")

        @app.route("/api/services")
        def services():
            return jsonify(self.service_mgr.all_services())

        @app.route("/api/modules")
        def modules():
            import json, glob, os
            MODULES_DIR = r"C:\OfflineHub\modules"
            result = {}
            if os.path.isdir(MODULES_DIR):
                for folder in sorted(os.listdir(MODULES_DIR)):
                    manifest_path = os.path.join(MODULES_DIR, folder, "manifest.json")
                    if os.path.exists(manifest_path):
                        try:
                            with open(manifest_path, encoding="utf-8") as f:
                                data = json.load(f)
                            svc_info = self.service_mgr.all_services().get(folder, {})
                            result[folder] = {
                                "name":        data.get("name", folder),
                                "emoji":       data.get("emoji", "📖"),
                                "description": data.get("description", ""),
                                "type":        data.get("type", "kiwix"),
                                "status":      svc_info.get("status", "stopped"),
                                "port":        svc_info.get("port"),
                                "format":      data.get("format", "raster")  # Used for MapLibre
                            }
                        except Exception:
                            pass
            return jsonify(result)

        @app.route("/api/ip")
        def ip():
            return jsonify({"ip": _local_ip()})

        # ── MBTiles tile endpoints ──────────────────────────────────────────
        @app.route("/tiles/<module>/<int:z>/<int:x>/<int:y>.png")
        def tile(module, z, x, y):
            from flask import abort, Response
            data = self.tile_server.get_tile(module, z, x, y)
            if data is None:
                abort(404)
            return Response(data, mimetype="image/png")

        @app.route("/tiles/<module>/<int:z>/<int:x>/<int:y>.pbf")
        def tile_pbf(module, z, x, y):
            from flask import abort, Response
            data = self.tile_server.get_tile(module, z, x, y)
            if data is None:
                abort(404)
            
            response = Response(data, mimetype="application/x-protobuf")
            
            # 🚀 FIX: Bulletproof GZIP check that won't crash on memoryview objects
            if len(data) >= 2 and data[0] == 0x1f and data[1] == 0x8b:
                response.headers['Content-Encoding'] = 'gzip'
                
            return response

        @app.route("/static/<path:filename>")
        def static_assets(filename):
            return send_from_directory(ASSETS_DIR, filename)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        port = self.config.get("portal_port", 8000)
        if not _port_available(port):
            port = _find_free_port(8000)
            self.config["portal_port"] = port

        from werkzeug.serving import make_server
        self._server = make_server("0.0.0.0", port, self.app)
        self._server.serve_forever()

    def stop(self):
        if self._server:
            self._server.shutdown()


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _find_free_port(start: int) -> int:
    for port in range(start, start + 200):
        if _port_available(port):
            return port
    return start