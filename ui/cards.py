"""
ModuleCard — one card per installed module displayed on the main screen.
Shows name, status indicator, and launch button.
"""

import threading
import webbrowser
import customtkinter as ctk


class ModuleCard(ctk.CTkFrame):

    STATUS_COLORS = {
        "running":  "#00aa44",
        "stopped":  "#555555",
        "starting": "#cc8800",
        "error":    "#cc2200",
    }

    def __init__(self, parent, folder: str, data: dict,
                 service_mgr, on_launch, **kwargs):
        super().__init__(parent, corner_radius=16, **kwargs)

        self.folder      = folder
        self.data        = data
        self.service_mgr = service_mgr
        self.on_launch   = on_launch

        self._build()
        self._poll_status()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self):
        # Left info column
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=20, pady=16)

        name_row = ctk.CTkFrame(info, fg_color="transparent")
        name_row.pack(anchor="w")

        ctk.CTkLabel(
            name_row,
            text=self.data.get("emoji", "📖"),
            font=ctk.CTkFont(size=28)
        ).pack(side="left")

        ctk.CTkLabel(
            name_row,
            text=f"  {self.data.get('name', self.folder)}",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(side="left")

        self.status_dot = ctk.CTkLabel(
            info,
            text="● Stopped",
            font=ctk.CTkFont(size=12),
            text_color=self.STATUS_COLORS["stopped"]
        )
        self.status_dot.pack(anchor="w", pady=(4, 0))

        desc = self.data.get("description", "")
        if desc:
            ctk.CTkLabel(
                info,
                text=desc,
                font=ctk.CTkFont(size=12),
                text_color="#aaaaaa",
                wraplength=600,
                justify="left"
            ).pack(anchor="w", pady=(2, 0))

        # Right button column
        btn_col = ctk.CTkFrame(self, fg_color="transparent")
        btn_col.pack(side="right", padx=20, pady=16)

        self.open_btn = ctk.CTkButton(
            btn_col,
            text="🌐  Open",
            width=140,
            height=50,
            fg_color="#007acc",
            hover_color="#005fa3",
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._launch
        )
        self.open_btn.pack()

    # ── Launch ────────────────────────────────────────────────────────────────

    def _launch(self):
        self.open_btn.configure(state="disabled", text="Starting…")
        self.status_dot.configure(text="● Starting…",
                                  text_color=self.STATUS_COLORS["starting"])
        threading.Thread(target=self._launch_thread, daemon=True).start()

    def _launch_thread(self):
        port, err = self.on_launch(self.folder, self.data)
        if err:
            self.after(0, lambda: self._show_error(err))
        elif port:
            webbrowser.open(f"http://127.0.0.1:{port}")
        self.after(0, lambda: self.open_btn.configure(
            state="normal", text="🌐  Open"
        ))

    def _show_error(self, message: str):
        from tkinter import messagebox
        messagebox.showerror(
            f"Could not start {self.data.get('name', self.folder)}",
            message
        )

    # ── Status polling ────────────────────────────────────────────────────────

    def _poll_status(self):
        status = self.service_mgr.get_status(self.folder)
        color  = self.STATUS_COLORS.get(status, "#555")
        label  = status.capitalize()
        self.status_dot.configure(text=f"● {label}", text_color=color)
        self.after(5_000, self._poll_status)