"""
SetupWizard — multi-step first-run experience.
Steps:  Welcome → Content → Hotspot → Password → Download → Done
"""

import hashlib
import threading
import customtkinter as ctk
from tkinter import messagebox

from core.downloader import Downloader, CATALOGUE
from core.hotspot    import HotspotManager


STEPS = ["Welcome", "Content", "Hotspot", "Password", "Download", "Done"]


class SetupWizard(ctk.CTk):

    def __init__(self, config: dict, save_config):
        super().__init__()

        self.config      = config
        self.save_config = save_config
        self.downloader  = Downloader()

        # User selections
        self.selected_content: dict[str, ctk.BooleanVar] = {}
        self.download_jobs: list = []   # (key, prog_widget, pct_var)

        self.title("Offline Hub — First Time Setup")
        self.geometry("700x560")
        self.resizable(False, False)

        self._step_index = 0
        self._container  = ctk.CTkFrame(self, fg_color="transparent")
        self._container.pack(fill="both", expand=True, padx=40, pady=30)

        self._nav = ctk.CTkFrame(self, fg_color="transparent")
        self._nav.pack(fill="x", padx=40, pady=(0, 20))

        self._back_btn = ctk.CTkButton(
            self._nav, text="◀ Back", width=120,
            fg_color="#333", command=self._back
        )
        self._back_btn.pack(side="left")

        self._next_btn = ctk.CTkButton(
            self._nav, text="Next ▶", width=120, command=self._next
        )
        self._next_btn.pack(side="right")

        self._show_step(0)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _show_step(self, idx: int):
        self._step_index = idx
        for w in self._container.winfo_children():
            w.destroy()

        builders = [
            self._step_welcome,
            self._step_content,
            self._step_hotspot,
            self._step_password,
            self._step_download,
            self._step_done,
        ]
        builders[idx]()

        self._back_btn.configure(
            state="normal" if idx > 0 else "disabled"
        )
        last = idx == len(STEPS) - 1
        self._next_btn.configure(
            text="Finish 🎉" if last else "Next ▶",
            command=self._finish if last else self._next
        )

    def _next(self):
        if not self._validate_step():
            return
        if self._step_index < len(STEPS) - 1:
            self._show_step(self._step_index + 1)

    def _back(self):
        if self._step_index > 0:
            self._show_step(self._step_index - 1)

    def _validate_step(self) -> bool:
        # Step 2 = Hotspot: save values before widgets are destroyed on navigate
        if self._step_index == 2:
            self.config["hotspot"]["ssid"]     = self._ssid_e.get()
            self.config["hotspot"]["password"] = self._hs_pw.get()

        # Step 3 = Password
        if self._step_index == 3:
            p1 = self._pw1.get()
            p2 = self._pw2.get()
            if len(p1) < 6:
                messagebox.showwarning("Password", "Password must be at least 6 characters.")
                return False
            if p1 != p2:
                messagebox.showwarning("Password", "Passwords do not match.")
                return False
            self.config["admin_password_hash"] = hashlib.pbkdf2_hmac(
                "sha256", p1.encode(), b"hubsalt", 200_000
            ).hex()
        return True

    # ── Steps ─────────────────────────────────────────────────────────────────

    def _step_welcome(self):
        ctk.CTkLabel(
            self._container,
            text="🏫  Welcome to Offline Hub",
            font=ctk.CTkFont(size=28, weight="bold")
        ).pack(pady=(20, 12))

        ctk.CTkLabel(
            self._container,
            text=(
                "This wizard will guide you through setting up your\n"
                "local knowledge server. Once configured, students can\n"
                "access Wikipedia, Khan Academy, books, and maps\n"
                "entirely offline — no internet required.\n\n"
                "Estimated disk space requirements:\n"
                "  • Wikipedia (mini)  ~10 GB\n"
                "  • Khan Academy (subset)  ~5–20 GB\n"
                "  • Project Gutenberg  ~60 GB\n"
                "  • OpenStreetMap region  ~1–10 GB"
            ),
            font=ctk.CTkFont(size=14),
            justify="left"
        ).pack(pady=10, anchor="w")

    def _step_content(self):
        ctk.CTkLabel(
            self._container,
            text="📦  Choose Content to Download",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(pady=(10, 16))

        for key, item in CATALOGUE.items():
            var = ctk.BooleanVar(value=False)
            self.selected_content[key] = var
            ctk.CTkCheckBox(
                self._container,
                text=f"{item['emoji']}  {item['name']}  —  {item['size']}",
                variable=var,
                font=ctk.CTkFont(size=14)
            ).pack(anchor="w", pady=6)

        ctk.CTkLabel(
            self._container,
            text="You can also download or add content later from the Admin Panel.",
            font=ctk.CTkFont(size=12),
            text_color="#888"
        ).pack(pady=(12, 0))

    def _step_hotspot(self):
        ctk.CTkLabel(
            self._container,
            text="📡  Wi-Fi Hotspot Settings",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(pady=(10, 16))

        form = ctk.CTkFrame(self._container, fg_color="transparent")
        form.pack(fill="x")

        ctk.CTkLabel(form, text="Network Name (SSID)",
                     width=200, anchor="w").grid(row=0, column=0, pady=8, sticky="w")
        self._ssid_e = ctk.CTkEntry(form, width=260)
        self._ssid_e.insert(0, self.config["hotspot"].get("ssid", "SchoolHub"))
        self._ssid_e.grid(row=0, column=1, pady=8)

        ctk.CTkLabel(form, text="Wi-Fi Password",
                     width=200, anchor="w").grid(row=1, column=0, pady=8, sticky="w")
        self._hs_pw = ctk.CTkEntry(form, width=260)
        self._hs_pw.insert(0, self.config["hotspot"].get("password", "schoolhub2024"))
        self._hs_pw.grid(row=1, column=1, pady=8)

        ctk.CTkLabel(
            self._container,
            text="Students connect to this network and open any browser\n"
                 "to reach the hub. Settings can be changed later.",
            font=ctk.CTkFont(size=12),
            text_color="#888",
            justify="left"
        ).pack(pady=(10, 0), anchor="w")

    def _step_password(self):
        ctk.CTkLabel(
            self._container,
            text="🔐  Set Admin Password",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(pady=(10, 16))

        ctk.CTkLabel(
            self._container,
            text="Choose a secure password for the Admin Panel.\n"
                 "This replaces the default password.",
            font=ctk.CTkFont(size=14),
            text_color="#aaa"
        ).pack(pady=(0, 16))

        form = ctk.CTkFrame(self._container, fg_color="transparent")
        form.pack()

        ctk.CTkLabel(form, text="New Password",
                     width=180, anchor="w").grid(row=0, column=0, pady=8)
        self._pw1 = ctk.CTkEntry(form, show="*", width=240)
        self._pw1.grid(row=0, column=1, pady=8)

        ctk.CTkLabel(form, text="Confirm Password",
                     width=180, anchor="w").grid(row=1, column=0, pady=8)
        self._pw2 = ctk.CTkEntry(form, show="*", width=240)
        self._pw2.grid(row=1, column=1, pady=8)

    def _step_download(self):
        ctk.CTkLabel(
            self._container,
            text="⬇️  Downloading Content",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(pady=(10, 16))

        selected = [k for k, v in self.selected_content.items() if v.get()]

        if not selected:
            ctk.CTkLabel(
                self._container,
                text="No content selected. Click Next to finish setup.\n"
                     "You can download content later from the Admin Panel.",
                font=ctk.CTkFont(size=14),
                text_color="#aaa"
            ).pack(pady=20)
            return

        scroll = ctk.CTkScrollableFrame(self._container, height=300)
        scroll.pack(fill="x")

        for key in selected:
            item = CATALOGUE[key]
            row  = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=5)

            ctk.CTkLabel(
                row,
                text=f"{item['emoji']}  {item['name']}",
                font=ctk.CTkFont(size=13), width=300, anchor="w"
            ).pack(side="left")

            prog = ctk.CTkProgressBar(row, width=180)
            prog.set(0)
            prog.pack(side="left", padx=6)

            pct_var = ctk.StringVar(value="0%")
            ctk.CTkLabel(row, textvariable=pct_var,
                         font=ctk.CTkFont(size=11), width=50).pack(side="left")

            self.download_jobs.append((key, prog, pct_var))

        self._next_btn.configure(state="disabled")

        def run_downloads():
            completed = [False] * len(self.download_jobs)

            def make_callbacks(i, p, v):
                def progress_cb(pct, _speed):
                    p.set(pct / 100)
                    v.set(f"{pct:.0f}%")
                def done_cb(success, path):
                    completed[i] = True
                    v.set("✓" if success else "✗")
                    if all(completed):
                        self.after(0, lambda: self._next_btn.configure(
                            state="normal"
                        ))
                return progress_cb, done_cb

            for idx, (key, prog, pct_var) in enumerate(self.download_jobs):
                item      = CATALOGUE[key]
                pcb, dcb  = make_callbacks(idx, prog, pct_var)
                threading.Thread(
                    target=self.downloader.download,
                    args=(item["url"], item["dest"], pcb, dcb,
                          item.get("checksum")),
                    daemon=True
                ).start()

        threading.Thread(target=run_downloads, daemon=True).start()

    def _step_done(self):
        ctk.CTkLabel(
            self._container,
            text="🎉  Setup Complete!",
            font=ctk.CTkFont(size=28, weight="bold")
        ).pack(pady=(30, 16))

        ip   = HotspotManager(self.config).get_local_ip()
        port = self.config.get("portal_port", 8000)

        ctk.CTkLabel(
            self._container,
            text=(
                f"Your hub is ready.\n\n"
                f"Students can access it at:\n"
                f"  http://{ip}:{port}\n\n"
                f"Use  Ctrl + Shift + A  to open the Admin Panel at any time."
            ),
            font=ctk.CTkFont(size=15),
            justify="left"
        ).pack(pady=10, anchor="center")

    # ── Finish ────────────────────────────────────────────────────────────────

    def _finish(self):
        # Hotspot values were already saved to self.config in _validate_step
        # when the user clicked Next past the Hotspot step.
        self.config["first_run"] = False
        self.save_config(self.config)
        self.destroy()

        from ui.app import OfflineHub
        app = OfflineHub(self.config, self.save_config)
        app.mainloop()