"""Minimal GUI window for eLORETA/sLORETA source localization."""

from __future__ import annotations

import customtkinter as ctk


class ELORETATool(ctk.CTkToplevel):
    """Placeholder window for source localization functionality."""

    def __init__(self, master):
        super().__init__(master)
        # Keep this window above its parent
        self.transient(master)
        self.title("eLORETA/sLORETA Source Localization")
        self.geometry("900x700")
        self.lift()
        self.attributes('-topmost', True)
        self.after(0, lambda: self.attributes('-topmost', False))
        self.focus_force()
        self._build_ui()

    def _build_ui(self) -> None:
        pad = 10
        ctk.CTkLabel(
            self,
            text="eLORETA/sLORETA Source Localization",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(pady=(pad, 0))
        msg = (
            "This is a placeholder for the eLORETA/sLORETA\n"
            "source localization tool. Functionality will be\n"
            "implemented in future updates."
        )
        ctk.CTkLabel(self, text=msg, justify="left").pack(padx=pad, pady=pad)
        ctk.CTkButton(self, text="Close", command=self.destroy).pack(pady=(0, pad))
