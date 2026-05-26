"""
table_widget.py
───────────────
Owns the Treeview, scrollbars, chunked-insert, and loading animation.
Decoupled from the main window — communicates only via callbacks.
"""

import tkinter as tk
import tkinter.ttk as ttk
from typing import Callable, Optional

from config import AppConfig
from record_processor import RecordProcessor


class TableWidget:

    _SPINNERS = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

    def __init__(
        self,
        parent: tk.Frame,
        config: AppConfig,
        on_row_double_click: Callable,
        on_sort: Callable,
        on_render_complete: Callable,
        on_render_progress: Callable,
    ):
        self._parent              = parent
        self._cfg                 = config
        self._on_row_double_click = on_row_double_click
        self._on_sort             = on_sort
        self._on_render_complete  = on_render_complete
        self._on_render_progress  = on_render_progress

        self._tree:          Optional[ttk.Treeview] = None
        self._col_widths:    dict = {}
        self._chunk_gen:     int  = 0
        self._anim_id:       Optional[str] = None
        self._loading_label: Optional[tk.Label] = None

        self._build_style()

    # ── Style ─────────────────────────────────────────────────
    def _build_style(self):
        C = self._cfg.colors
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "KV.Treeview",
            background=C["bg_row_even"], foreground=C["text_main"],
            fieldbackground=C["bg_dark"], bordercolor=C["border"],
            rowheight=28, font=self._cfg.fonts["table"],
        )
        style.configure(
            "KV.Treeview.Heading",
            background=C["bg_input"], foreground=C["accent"],
            font=self._cfg.fonts["table_h"], relief="flat", borderwidth=0,
        )
        style.map("KV.Treeview",
            background=[("selected", C["selection"])],
            foreground=[("selected", C["accent_soft"])],
        )
        style.map("KV.Treeview.Heading",
            background=[("active", C["border"])],
            foreground=[("active", C["accent_glow"])],
        )
        for orient in ("Vertical", "Horizontal"):
            style.configure(
                f"KV.{orient}.TScrollbar",
                background=C["bg_input"], troughcolor=C["bg_dark"],
                arrowcolor=C["text_sub"], bordercolor=C["border"], relief="flat",
            )

    # ── Loading state ─────────────────────────────────────────
    def show_loading(self):
        self._clear()
        C    = self._cfg.colors
        card = tk.Frame(self._parent, bg=C["bg_card"], padx=40, pady=30, relief="flat")
        card.place(relx=0.5, rely=0.5, anchor="center")
        self._loading_label = tk.Label(
            card, text="⠋  Fetching records from Kintone…",
            font=("Segoe UI", 13), fg=C["accent"], bg=C["bg_card"],
        )
        self._loading_label.pack()
        tk.Label(card, text="Please wait while data loads",
                 font=("Segoe UI", 9), fg=C["text_dim"], bg=C["bg_card"]).pack(pady=(4, 0))
        self._animate(0)

    def _animate(self, i: int):
        if not self._loading_label or not self._loading_label.winfo_exists():
            return
        self._loading_label.config(
            text=f"{self._SPINNERS[i % len(self._SPINNERS)]}  Fetching records from Kintone…"
        )
        self._anim_id = self._parent.after(80, lambda: self._animate(i + 1))

    def stop_loading(self):
        if self._anim_id:
            self._parent.after_cancel(self._anim_id)
            self._anim_id = None

    def show_error(self, message: str):
        self._clear()
        C    = self._cfg.colors
        card = tk.Frame(self._parent, bg=C["bg_card"], padx=30, pady=24)
        card.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(card, text="✕  Connection Error",
                 font=("Segoe UI", 13, "bold"), fg=C["danger"], bg=C["bg_card"]).pack()
        tk.Label(card, text=message, font=("Consolas", 10), fg=C["text_sub"],
                 bg=C["bg_card"], justify="left", wraplength=560).pack(pady=(10, 0))
        tk.Label(card, text="Check credentials in config.py.",
                 font=("Segoe UI", 9), fg=C["text_dim"], bg=C["bg_card"]).pack(pady=(8, 0))

    # ── Render ────────────────────────────────────────────────
    def render(self, records: list, fields: list, label_fn: Callable):
        """Full render: build Treeview from scratch."""
        self._clear()
        C = self._cfg.colors

        if not records:
            card = tk.Frame(self._parent, bg=C["bg_card"], padx=30, pady=24)
            card.place(relx=0.5, rely=0.5, anchor="center")
            tk.Label(card, text="◎  No records found in this application.",
                     font=("Segoe UI", 12), fg=C["text_sub"], bg=C["bg_card"]).pack()
            return

        container = tk.Frame(self._parent, bg=C["bg_dark"])
        container.pack(fill="both", expand=True)

        vsb = ttk.Scrollbar(container, orient="vertical",   style="KV.Vertical.TScrollbar")
        hsb = ttk.Scrollbar(container, orient="horizontal", style="KV.Horizontal.TScrollbar")
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")

        self._tree = ttk.Treeview(
            container, columns=fields, show="headings",
            style="KV.Treeview", yscrollcommand=vsb.set,
            xscrollcommand=hsb.set, selectmode="browse",
        )
        self._tree.pack(fill="both", expand=True)
        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)

        # Measure column widths from first 200 rows
        self._col_widths = {}
        for col in fields:
            max_len = len(label_fn(col))
            for rec in records[:200]:
                max_len = max(max_len, len(RecordProcessor.cell_value(rec, col)))
            self._col_widths[col] = min(max(max_len * 8 + 20, 80), 260)

        for col in fields:
            self._tree.heading(col, text=f"  {label_fn(col)}",
                               command=lambda c=col: self._on_sort(c))
            self._tree.column(col, width=self._col_widths[col], minwidth=60, anchor="w")

        self._tree.tag_configure("even", background=C["bg_row_even"], foreground=C["text_main"])
        self._tree.tag_configure("odd",  background=C["bg_row_odd"],  foreground=C["text_main"])
        self._tree.bind("<Double-1>", lambda e: self._on_row_double_click(e))

        self._chunk_gen += 1
        self._insert_chunk(records, fields, 0, gen=self._chunk_gen)

    def repopulate(self, records: list, fields: list):
        """Fast re-fill of an existing Treeview (search / sort)."""
        if not self._tree or not self._tree.winfo_exists():
            return
        self._chunk_gen += 1
        self._tree.delete(*self._tree.get_children())
        self._on_render_progress("Rendering rows…")
        self._insert_chunk(records, fields, 0, gen=self._chunk_gen)

    def _insert_chunk(self, records: list, fields: list,
                      start: int, chunk: int = 100, gen: int = 0):
        if gen != self._chunk_gen:
            return
        end = min(start + chunk, len(records))
        for i in range(start, end):
            values = [RecordProcessor.cell_value(records[i], col) for col in fields]
            tag    = "even" if i % 2 == 0 else "odd"
            self._tree.insert("", "end", iid=str(i), values=values, tags=(tag,))

        self._on_render_progress(f"Rendering…  {end:,} / {len(records):,} rows")

        if end < len(records):
            self._parent.after(0, lambda: self._insert_chunk(records, fields, end, chunk, gen))
        else:
            self._on_render_complete(records, fields)

    # ── Sort heading arrows ───────────────────────────────────
    def update_sort_arrows(self, fields: list, sort_col: str,
                           sort_rev: bool, label_fn: Callable):
        if not self._tree:
            return
        for c in fields:
            arrow = ("  ▲" if not sort_rev else "  ▼") if c == sort_col else ""
            self._tree.heading(c, text=f"  {label_fn(c)}{arrow}")

    # ── Responsive column resize ──────────────────────────────
    def resize_columns(self, fields: list, tree_width: int):
        if not self._tree or not self._tree.winfo_exists() or not fields:
            return
        total_base = sum(self._col_widths.get(c, 100) for c in fields)
        if total_base > 0:
            for col in fields:
                base  = self._col_widths.get(col, 100)
                new_w = max(60, int(tree_width * base / total_base))
                self._tree.column(col, width=new_w)

    # ── Font refresh ──────────────────────────────────────────
    def refresh_style(self, fonts: dict):
        style = ttk.Style()
        style.configure("KV.Treeview",         font=fonts["table"])
        style.configure("KV.Treeview.Heading", font=fonts["table_h"])

    # ── Accessor ──────────────────────────────────────────────
    def focused_item(self) -> Optional[str]:
        return self._tree.focus() if self._tree else None

    # ── Private ───────────────────────────────────────────────
    def _clear(self):
        for w in self._parent.winfo_children():
            w.destroy()
        self._tree = None
