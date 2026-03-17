"""
Main application window.
Shows the module grid and starts background services.
"""

import threading
import customtkinter as ctk

from core.service_manager import ServiceManager
from core.module_manager  import ModuleManager
from core.hotspot          import HotspotManager
from core.portal           import PortalServer
from ui.cards              import ModuleCard
from ui.admin_panel        import AdminPanel


class OfflineHub(ctk.CTk):

    def __init__(self, config: dict, save_config):
        super().__init__()

        self.config      = config
        self.save_config = save_config

        self.title("Offline School Knowledge Hub")
        self.geometry("1100x740")
        self.resizable(True, True)

        self.service_mgr = ServiceManager()
        self.module_mgr  = ModuleManager(self.service_mgr)
        self.hotspot_mgr = HotspotManager(config)
        self.portal      = PortalServer(config, self.service_mgr)

        self._build_ui()
        self.load_modules()

        # Start portal server
        threading.Thread(target=self.portal.start, daemon=True).start()

        # Auto-start hotspot if configured
        if config["hotspot"].get("enabled"):
            threading.Thread(
                target=self.hotspot_mgr.start, daemon=True
            ).start()

        # Health-check loop
        threading.Thread(target=self._health_loop, daemon=True).start()

        # Admin shortcut
        self.bind_all("<Control-Shift-A>", self._open_admin_prompt)

        # Clean shutdown
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header row
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=30, pady=(20, 5))

        ctk.CTkLabel(
            hdr,
            text="🏫 Offline School Knowledge Hub",
            font=ctk.CTkFont(size=30, weight="bold")
        ).pack(side="left")

        # Status bar (hotspot / portal)
        self.status_var = ctk.StringVar(value="")
        ctk.CTkLabel(
            hdr,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=13),
            text_color="#888"
        ).pack(side="right", padx=10)

        self._update_status_bar()

        # Scrollable module grid
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.pack(fill="both", expand=True, padx=30, pady=10)

    def _update_status_bar(self):
        ip      = self.hotspot_mgr.get_local_ip()
        hs      = "🟢 Hotspot ON" if self.hotspot_mgr.is_running() else "🔴 Hotspot OFF"
        port    = self.config.get("portal_port", 8000)
        self.status_var.set(f"{hs}  |  Portal → http://{ip}:{port}")
        self.after(15_000, self._update_status_bar)

    # ── Module loading ────────────────────────────────────────────────────────

    def load_modules(self):
        for w in self.scroll_frame.winfo_children():
            w.destroy()

        modules = self.module_mgr.list_modules()

        if not modules:
            ctk.CTkLabel(
                self.scroll_frame,
                text="No modules installed.\nOpen Admin Panel (Ctrl+Shift+A) to add content.",
                font=ctk.CTkFont(size=16),
                text_color="#888"
            ).pack(pady=60)
            return

        for folder, data in modules:
            card = ModuleCard(
                self.scroll_frame,
                folder=folder,
                data=data,
                service_mgr=self.service_mgr,
                on_launch=self.module_mgr.launch_module
            )
            card.pack(fill="x", pady=8, padx=10)

    # ── Health loop ───────────────────────────────────────────────────────────

    def _health_loop(self):
        import time
        while True:
            time.sleep(30)
            self.service_mgr.health_check_all()

    # ── Admin ─────────────────────────────────────────────────────────────────

    def _open_admin_prompt(self, event=None):
        win = ctk.CTkToplevel(self)
        win.title("Admin Access")
        win.geometry("420x260")
        win.grab_set()
        win.after(50, win.lift)

        ctk.CTkLabel(
            win,
            text="Enter Admin Password",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(pady=20)

        entry = ctk.CTkEntry(win, show="*", width=280)
        entry.pack(pady=10)
        win.after(100, entry.focus_force)

        msg_var = ctk.StringVar()
        ctk.CTkLabel(win, textvariable=msg_var, text_color="red").pack()

        def check():
            import hashlib
            pw   = entry.get()
            stored = self.config.get("admin_password_hash", "")
            hashed = hashlib.pbkdf2_hmac(
                "sha256", pw.encode(), b"hubsalt", 200_000
            ).hex()
            if hashed == stored:
                win.destroy()
                AdminPanel(self, self.config, self.save_config,
                           self.module_mgr, self.hotspot_mgr,
                           self.service_mgr, self.load_modules)
            else:
                entry.delete(0, "end")
                msg_var.set("Incorrect password.")

        entry.bind("<Return>", lambda e: check())
        ctk.CTkButton(win, text="Login", command=check).pack(pady=15)

    # ── Shutdown ──────────────────────────────────────────────────────────────

    def _on_close(self):
        self.service_mgr.stop_all()
        self.hotspot_mgr.stop()
        self.portal.stop()
        self.destroy()