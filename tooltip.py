"""
tooltip.py
──────────
Lightweight hover tooltip for any tkinter widget.
"""

import tkinter as tk
from typing import Callable


class Tooltip:

    def __init__(self, widget: tk.Widget, text_fn: Callable[[], str]):
        self._widget  = widget
        self._text_fn = text_fn
        self._tip_win = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self._tip_win:
            return
        text = self._text_fn()
        if not text:
            return
        x = self._widget.winfo_rootx()
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip_win = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.configure(bg="#D4E1F1")
        tk.Label(
            tw, text=text, justify="left", font=("Segoe UI", 9),
            fg="#1B2532", bg="#FFFFFF", relief="flat", bd=0, padx=12, pady=8,
        ).pack(padx=1, pady=1)

    def _hide(self, _event=None):
        if self._tip_win:
            self._tip_win.destroy()
            self._tip_win = None
