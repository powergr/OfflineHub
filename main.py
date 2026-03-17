"""
Offline School Knowledge Hub — Entry Point
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

# ── Extract vendor binaries on first run ─────────────────────────────────────
def extract_vendor():
    r"""Copy bundled vendor binaries to C:\OfflineHub\bin if not already there."""
    if getattr(sys, "frozen", False):
        # Running as PyInstaller EXE — _MEIPASS holds the extracted bundle
        vendor_src = os.path.join(sys._MEIPASS, "vendor")
    else:
        vendor_src = os.path.join(os.path.dirname(__file__), "vendor")

    if not os.path.isdir(vendor_src):
        return

    for item in os.listdir(vendor_src):
        src  = os.path.join(vendor_src, item)
        dest = os.path.join(BIN_DIR, item)
        if not os.path.exists(dest):
            if os.path.isdir(src):
                from shutil import copytree
                copytree(src, dest)
            else:
                from shutil import copy2
                copy2(src, dest)

extract_vendor()

# ── Default config ────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "first_run": True,
    "version": "1.0.0",
    "admin_password_hash": "",          # set during wizard
    "hotspot": {
        "ssid": "SchoolHub",
        "password": "schoolhub2024",
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
        # Merge missing keys from default
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