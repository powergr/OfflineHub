"""
Admin Panel — tabbed window for content management, hotspot, services, settings.
"""

import hashlib
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.downloader import Downloader, CATALOGUE


class AdminPanel(ctk.CTkToplevel):

    def __init__(self, parent, config, save_config,
                 module_mgr, hotspot_mgr, service_mgr, refresh_cb):
        super().__init__(parent)

        self.config      = config
        self.save_config = save_config
        self.module_mgr  = module_mgr
        self.hotspot_mgr = hotspot_mgr
        self.service_mgr = service_mgr
        self.refresh_cb  = refresh_cb
        self.downloader  = Downloader()

        self.title("⚙️  Admin Panel")
        self.geometry("780x580")
        self.grab_set()
        self.after(50, self.lift)

        self._build_tabs()

    # ── Tab container ─────────────────────────────────────────────────────────

    def _build_tabs(self):
        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=16, pady=16)

        for name in ("Modules", "Hotspot", "Services", "Settings"):
            tabs.add(name)

        self._build_modules_tab(tabs.tab("Modules"))
        self._build_hotspot_tab(tabs.tab("Hotspot"))
        self._build_services_tab(tabs.tab("Services"))
        self._build_settings_tab(tabs.tab("Settings"))

    # ══════════════════════════════════════════════════════════════════════════
    # MODULES TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_modules_tab(self, tab):
        # ── Download section ─────────────────────────────────────────────────
        ctk.CTkLabel(
            tab, text="Download Content",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(12, 4))

        for key, item in CATALOGUE.items():
            row = ctk.CTkFrame(tab, fg_color="transparent")
            row.pack(fill="x", pady=3)

            ctk.CTkButton(
                row, text="⬇  Download", width=120,
                command=lambda k=key, p=None, v=None: self._start_download(k, p, v)
            ).pack(side="right", padx=(4, 0))

            pct_var = ctk.StringVar(value="")
            ctk.CTkLabel(row, textvariable=pct_var,
                         font=ctk.CTkFont(size=11), width=42).pack(side="right")

            prog = ctk.CTkProgressBar(row, width=130)
            prog.set(0)
            prog.pack(side="right", padx=6)

            # Rebind button now that prog and pct_var exist
            row.winfo_children()[0].configure(
                command=lambda k=key, p=prog, v=pct_var: self._start_download(k, p, v)
            )

            ctk.CTkLabel(
                row,
                text=f"{item['emoji']}  {item['name']}  ({item['size']})",
                font=ctk.CTkFont(size=13),
                anchor="w"
            ).pack(side="left", fill="x", expand=True)

        ctk.CTkFrame(tab, height=1, fg_color="#30363d").pack(fill="x", pady=12)

        # ── Manual add ───────────────────────────────────────────────────────
        ctk.CTkLabel(
            tab, text="Manual Install",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(0, 4))

        ctk.CTkButton(
            tab, text="📦  Add Module from ZIP",
            command=self._add_from_zip
        ).pack(fill="x", pady=4)

        ctk.CTkButton(
            tab, text="🗑  Remove Module",
            fg_color="#882222", hover_color="#aa3333",
            command=self._remove_module
        ).pack(fill="x", pady=4)

    def _start_download(self, key: str, prog, pct_var):
        item = CATALOGUE[key]

        def progress_cb(pct: float, speed_kbps: float):
            prog.set(pct / 100)
            pct_var.set(f"{pct:.0f}%")

        def done_cb(success: bool, path: str):
            if success:
                self.module_mgr.install_from_download(key, item, path)
                self.refresh_cb()
                pct_var.set("✓")
            else:
                pct_var.set("✗")

        threading.Thread(
            target=self.downloader.download,
            args=(item["url"], item["dest"], progress_cb, done_cb,
                  item.get("checksum")),
            daemon=True
        ).start()

    def _add_from_zip(self):
        zip_path = filedialog.askopenfilename(
            title="Select Module ZIP file",
            filetypes=[("ZIP files", "*.zip")]
        )
        if not zip_path:
            return

        try:
            # 🚀 Uses the new, smart extraction function from module_manager
            self.module_mgr.install_from_zip(zip_path)
            self.refresh_cb()
            messagebox.showinfo("Success", "Module installed and started successfully.")
        except Exception as e:
            messagebox.showerror("Install Error", str(e))

    def _remove_module(self):
        from core.module_manager import MODULES_DIR # 🚀 Safely imported to prevent Nuitka crash
        folder = filedialog.askdirectory(
            initialdir=MODULES_DIR, title="Select module to remove"
        )
        if not folder:
            return
        try:
            self.module_mgr.remove(folder)
            self.refresh_cb()
            messagebox.showinfo("Removed", "Module deleted.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ══════════════════════════════════════════════════════════════════════════
    # HOTSPOT TAB (unchanged logic)
    # ══════════════════════════════════════════════════════════════════════════

    def _build_hotspot_tab(self, tab):
        from core.hotspot import is_admin, restart_as_admin
        hs = self.config["hotspot"]

        ctk.CTkLabel(tab, text="Wi-Fi Hotspot",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(12, 8))

        if not is_admin():
            warn = ctk.CTkFrame(tab, fg_color="#3a1a00", corner_radius=8)
            warn.pack(fill="x", padx=10, pady=(0, 10))
            ctk.CTkLabel(
                warn,
                text="⚠️  Hotspot control requires administrator rights.",
                font=ctk.CTkFont(size=12), text_color="#ffaa44"
            ).pack(side="left", padx=12, pady=8)
            ctk.CTkButton(
                warn, text="🔒 Restart as Admin", width=160,
                fg_color="#cc6600", hover_color="#ee7700",
                command=lambda: (restart_as_admin(), self.master.after(500, self.master._on_close))
            ).pack(side="right", padx=8, pady=6)

        form = ctk.CTkFrame(tab, fg_color="transparent")
        form.pack(fill="x", padx=20)

        ctk.CTkLabel(form, text="SSID", width=100, anchor="w").grid(
            row=0, column=0, pady=6, sticky="w")
        self.ssid_entry = ctk.CTkEntry(form, width=280)
        self.ssid_entry.insert(0, hs.get("ssid", "SchoolHub"))
        self.ssid_entry.grid(row=0, column=1, pady=6)

        ctk.CTkLabel(form, text="Password", width=100, anchor="w").grid(
            row=1, column=0, pady=6, sticky="w")
        self.pw_entry = ctk.CTkEntry(form, width=280, show="*")
        self.pw_entry.insert(0, hs.get("password", ""))
        self.pw_entry.grid(row=1, column=1, pady=6)

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(pady=16)

        ctk.CTkButton(
            btn_row, text="💾  Save", width=130,
            command=self._save_hotspot
        ).pack(side="left", padx=8)

        self.hs_toggle_btn = ctk.CTkButton(
            btn_row,
            text="🟢 Stop Hotspot" if self.hotspot_mgr.is_running()
                 else "▶ Start Hotspot",
            width=160,
            fg_color="#005500" if self.hotspot_mgr.is_running() else "#334",
            command=self._toggle_hotspot
        )
        self.hs_toggle_btn.pack(side="left", padx=8)

        ctk.CTkButton(
            btn_row, text="⚙️ Windows Settings", width=160,
            fg_color="#333355", hover_color="#444477",
            command=self.hotspot_mgr.open_windows_hotspot_settings
        ).pack(side="left", padx=8)

        self.hs_status = ctk.CTkLabel(
            tab, text="", font=ctk.CTkFont(size=12), text_color="#aaa"
        )
        self.hs_status.pack()
        self._refresh_hs_status()

        ctk.CTkFrame(tab, height=1, fg_color="#30363d").pack(fill="x", pady=12)

        ctk.CTkLabel(tab, text="Connected Devices",
                     font=ctk.CTkFont(size=14, weight="bold")).pack()

        self.devices_box = ctk.CTkTextbox(tab, height=100)
        self.devices_box.pack(fill="x", padx=20, pady=6)

        ctk.CTkButton(
            tab, text="🔄  Refresh Devices",
            command=self._refresh_devices
        ).pack(pady=4)

    def _save_hotspot(self):
        self.config["hotspot"]["ssid"]     = self.ssid_entry.get()
        self.config["hotspot"]["password"] = self.pw_entry.get()
        self.save_config(self.config)
        messagebox.showinfo("Saved", "Hotspot settings saved.")

    def _toggle_hotspot(self):
        if self.hotspot_mgr.is_running():
            self.hotspot_mgr.stop()
            self.config["hotspot"]["enabled"] = False
        else:
            ok, msg = self.hotspot_mgr.start()
            self.config["hotspot"]["enabled"] = ok
            if not ok:
                messagebox.showerror("Hotspot Error", msg)
        self.save_config(self.config)
        self._refresh_hs_status()

    def _refresh_hs_status(self):
        running = self.hotspot_mgr.is_running()
        ip      = self.hotspot_mgr.get_local_ip()
        self.hs_status.configure(
            text=f"Status: {'Running' if running else 'Stopped'}  |  IP: {ip}"
        )
        self.hs_toggle_btn.configure(
            text="🟢 Stop Hotspot" if running else "▶ Start Hotspot"
        )

    def _refresh_devices(self):
        devices = self.hotspot_mgr.list_connected_devices()
        self.devices_box.configure(state="normal")
        self.devices_box.delete("1.0", "end")
        if devices:
            self.devices_box.insert("end", "\n".join(devices))
        else:
            self.devices_box.insert("end", "No devices connected.")
        self.devices_box.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    # SERVICES TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_services_tab(self, tab):
        ctk.CTkLabel(tab, text="Installed Modules & Services",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(12, 8))

        ctk.CTkLabel(
            tab,
            text="Modules appear here once installed. Click Open on the main screen to start one.",
            font=ctk.CTkFont(size=12), text_color="#888", wraplength=500
        ).pack(pady=(0, 8))

        self.svc_frame = ctk.CTkScrollableFrame(tab)
        self.svc_frame.pack(fill="both", expand=True, padx=10)

        ctk.CTkButton(
            tab, text="🔄  Refresh", command=self._refresh_services
        ).pack(pady=8)

        self._refresh_services()

    def _refresh_services(self):
        for w in self.svc_frame.winfo_children():
            w.destroy()

        import json, os
        from core.module_manager import MODULES_DIR # 🚀 Safer Nuitka import

        modules = []
        if os.path.isdir(MODULES_DIR):
            for folder in sorted(os.listdir(MODULES_DIR)):
                manifest_path = os.path.join(MODULES_DIR, folder, "manifest.json")
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, encoding="utf-8") as f:
                            data = json.load(f)
                        modules.append((folder, data))
                    except Exception:
                        pass

        if not modules:
            ctk.CTkLabel(self.svc_frame,
                         text="No modules installed yet.",
                         text_color="#888").pack(pady=20)
            return

        for folder, data in modules:
            status = self.service_mgr.get_status(folder)
            port   = self.service_mgr.get_port(folder)
            running = status == "running"

            row = ctk.CTkFrame(self.svc_frame, corner_radius=8)
            row.pack(fill="x", pady=4, padx=4)

            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="both", expand=True, padx=12, pady=8)

            name_label = f"{data.get('emoji','📖')}  {data.get('name', folder)}"
            ctk.CTkLabel(
                left, text=name_label,
                font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
            ).pack(anchor="w")

            port_text = f"Port {port}" if port else "Not running"
            status_color = "#3fb950" if running else "#888888"
            ctk.CTkLabel(
                left,
                text=f"● {status.capitalize()}  —  {port_text}",
                font=ctk.CTkFont(size=11),
                text_color=status_color, anchor="w"
            ).pack(anchor="w")

            if running:
                right = ctk.CTkFrame(row, fg_color="transparent")
                right.pack(side="right", padx=8, pady=8)

                ctk.CTkButton(
                    right, text="Stop", width=80, height=30,
                    fg_color="#552222", hover_color="#772222",
                    command=lambda n=folder: self._stop_service(n)
                ).pack(side="left", padx=4)

                ctk.CTkButton(
                    right, text="Restart", width=80, height=30,
                    command=lambda n=folder: self._restart_service(n)
                ).pack(side="left", padx=4)

    def _stop_service(self, name):
        self.service_mgr.stop(name)
        self._refresh_services()

    def _restart_service(self, name):
        self.service_mgr.restart(name)
        self._refresh_services()

    # ══════════════════════════════════════════════════════════════════════════
    # SETTINGS TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_settings_tab(self, tab):
        ctk.CTkLabel(tab, text="General Settings",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(12, 8))

        form = ctk.CTkFrame(tab, fg_color="transparent")
        form.pack(fill="x", padx=20)

        ctk.CTkLabel(form, text="Portal Port", width=160,
                     anchor="w").grid(row=0, column=0, pady=8, sticky="w")
        self.port_entry = ctk.CTkEntry(form, width=120)
        self.port_entry.insert(0, str(self.config.get("portal_port", 8000)))
        self.port_entry.grid(row=0, column=1, pady=8)

        ctk.CTkLabel(form, text="Start on Boot", width=160,
                     anchor="w").grid(row=1, column=0, pady=8, sticky="w")
        self.autostart_switch = ctk.CTkSwitch(form, text="")
        if self.config.get("autostart"):
            self.autostart_switch.select()
        self.autostart_switch.grid(row=1, column=1, pady=8, sticky="w")

        ctk.CTkLabel(form, text="Version", width=160,
                     anchor="w").grid(row=2, column=0, pady=8, sticky="w")
        ctk.CTkLabel(form, text=self.config.get("version", "1.0.0"),
                     font=ctk.CTkFont(size=13), text_color="#888",
                     anchor="w").grid(row=2, column=1, pady=8, sticky="w")

        ctk.CTkFrame(tab, height=1, fg_color="#30363d").pack(fill="x", pady=12)

        ctk.CTkLabel(tab, text="Change Admin Password",
                     font=ctk.CTkFont(size=15, weight="bold")).pack()

        pw_form = ctk.CTkFrame(tab, fg_color="transparent")
        pw_form.pack(fill="x", padx=20, pady=6)

        ctk.CTkLabel(pw_form, text="New Password",
                     width=160, anchor="w").grid(row=0, column=0, pady=6)
        self.new_pw1 = ctk.CTkEntry(pw_form, show="*", width=220)
        self.new_pw1.grid(row=0, column=1, pady=6)

        ctk.CTkLabel(pw_form, text="Confirm",
                     width=160, anchor="w").grid(row=1, column=0, pady=6)
        self.new_pw2 = ctk.CTkEntry(pw_form, show="*", width=220)
        self.new_pw2.grid(row=1, column=1, pady=6)

        self.pw_msg = ctk.CTkLabel(tab, text="", text_color="#cc4444")
        self.pw_msg.pack()

        ctk.CTkButton(
            tab, text="💾  Save All Settings",
            command=self._save_settings
        ).pack(pady=16)

    def _save_settings(self):
        try:
            self.config["portal_port"] = int(self.port_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Port must be a number.")
            return

        self.config["autostart"] = bool(self.autostart_switch.get())
        if self.config["autostart"]:
            self._register_autostart()

        p1, p2 = self.new_pw1.get(), self.new_pw2.get()
        if p1 or p2:
            if p1 != p2:
                self.pw_msg.configure(text="Passwords do not match.")
                return
            if len(p1) < 6:
                self.pw_msg.configure(text="Password must be ≥ 6 characters.")
                return
            self.config["admin_password_hash"] = hashlib.pbkdf2_hmac(
                "sha256", p1.encode(), b"hubsalt", 200_000
            ).hex()

        self.save_config(self.config)
        messagebox.showinfo("Saved", "Settings saved.")

    def _register_autostart(self):
        import sys, winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, "OfflineHub", 0, winreg.REG_SZ,
                              sys.executable)
            winreg.CloseKey(key)
        except Exception as e:
            messagebox.showwarning("Autostart", f"Could not register autostart: {e}")