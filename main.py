"""
Offline Knowledge Hub — Entry Point
Handles first-run detection and launches the correct UI flow.
"""

import os
import sys
import json

# ── Ensure C:\OfflineHub directory tree exists ──────────────────────────────
BASE_DIR     = r"C:\OfflineHub"
MODULES_DIR  = os.path.join(BASE_DIR, "modules")
BIN_DIR      = os.path.join(BASE_DIR, "bin")
CONFIG_PATH  = os.path.join(BASE_DIR, "config.json")

for d in (BASE_DIR, MODULES_DIR, BIN_DIR):
    os.makedirs(d, exist_ok=True)

# NOTE: extract_vendor() has been removed. 
# The Setup.exe installer now securely handles placing vendor binaries into BIN_DIR.

# ── Default config ────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "first_run": True,
    "version": "0.1.2",
    "admin_password_hash": "",          
    "hotspot": {
        "ssid": "OfflineHub",
        "password": "offlinehub2026",
        "enabled": False
    },
    "portal_port": 8000,
    "autostart": False,
    "modules": {}
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            data.setdefault(k, v)
        return data
    return dict(DEFAULT_CONFIG)

def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

# ── Launch ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import customtkinter as ctk

    config = load_config()

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    if config.get("first_run", True):
        from ui.wizard import SetupWizard
        app = SetupWizard(config, save_config)
    else:
        from ui.app import OfflineHub
        app = OfflineHub(config, save_config)

    app.mainloop()