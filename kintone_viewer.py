"""
kintone_viewer.py
─────────────────
Top-level application window.
Orchestrates all service and widget classes — owns no business logic itself.
"""

import threading
from datetime import datetime
from typing import Optional

import tkinter as tk
import tkinter.ttk as ttk
import customtkinter as ctk

from config import AppConfig
from field_mapping import (
    ACTIVE_MAP, CONFIRMED_CODES, LABEL_TO_SS,
    PENDING_FIELDS, TOTAL_FIELDS, FIELD_MAP,
)
from font_manager import FontManager
from kintone_api import KintoneAPI
from record_processor import RecordProcessor
from smartsheet_api import SmartsheetAPI
from table_widget import TableWidget
from tooltip import Tooltip


class KintoneViewer(ctk.CTk):

    def __init__(self, config: Optional[AppConfig] = None):
        super().__init__()

        self._cfg    = config or AppConfig()
        self._C      = self._cfg.colors  # shortcut used throughout

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.title("AUTOMATION TOOL ✦  SYNC DATA VIEWER")
        self.geometry("1280x780")
        self.minsize(900, 600)
        self.configure(fg_color=self._C["bg_dark"])

        # ── State ─────────────────────────────────────────────
        self._all_records:      list          = []
        self._field_codes:      list          = []
        self._sort_col:         Optional[str] = None
        self._sort_rev:         bool          = False
        self._filter_text:      str           = ""
        self._date_desc:        bool          = True
        self._last_width:       int           = 1280
        self._col_tooltip_text: str           = ""
        self._view_mode:        str           = "full"    # "full" or "selected"

        # ── Service layer ─────────────────────────────────────
        self._kintone_api  = KintoneAPI(self._cfg)
        self._ss_api       = SmartsheetAPI(self._cfg)
        self._field_labels = self._kintone_api.fetch_field_labels()
        self._field_order  = self._kintone_api.fetch_field_layout()

        # ── Build UI then start loading ───────────────────────
        self._build_ui()
        self.after(200, self._start_fetch)

    # ═════════════════════════════════════════
    #  UI  BUILD
    # ═════════════════════════════════════════
    def _build_ui(self):
        f = FontManager.scale(self._last_width)
        C = self._C

        # ── Header bar ────────────────────────────────────────
        self._top_bar = tk.Frame(self, bg=C["header_bg"], height=64)
        self._top_bar.pack(fill="x", side="top")
        self._top_bar.pack_propagate(False)

        tk.Label(self._top_bar, text="●", font=("Segoe UI", 22),
                 fg=C["accent"], bg=C["header_bg"]).pack(side="left", padx=(20, 4), pady=14)

        self._lbl_title = tk.Label(
            self._top_bar, text="sync tool for Kintone and Smartsheet",
            font=f["title"], fg=C["text_main"], bg=C["header_bg"],
        )
        self._lbl_title.pack(side="left", pady=14)

        tk.Label(
            self._top_bar, text=f" APP #{self._cfg.kintone_app_id} ",
            font=("Segoe UI", 9, "bold"),
            fg=C["accent"], bg=C["bg_input"], relief="flat", padx=6, pady=3,
        ).pack(side="left", padx=12)

        self._lbl_time = tk.Label(self._top_bar, text="",
                                  font=f["mono"], fg=C["text_dim"], bg=C["header_bg"])
        self._lbl_time.pack(side="right", padx=20)

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # ── Sub-bar ───────────────────────────────────────────
        sub_outer = tk.Frame(self, bg=C["bg_card"])
        sub_outer.pack(fill="x")

        self._sub_top = tk.Frame(sub_outer, bg=C["bg_card"])
        self._sub_top.pack(fill="x", padx=12, pady=(6, 2))

        self._btn_refresh = self._make_btn(
            "↺  Refresh", C["bg_card"], C["accent"], C["accent_soft"],
            self._start_fetch, f)
        self._btn_refresh.pack(side="left", padx=(0, 6))

        self._btn_order = self._make_btn(
            "↕  Newest First", C["bg_card"], C["accent_soft"], C["accent"],
            self._toggle_order, f)
        self._btn_order.pack(side="left", padx=(0, 6))

        self._btn_export = tk.Button(
            self._sub_top, text="⬇  PUSH TO SMARTSHEET", font=f["btn"],
            fg=C["accent"], bg=C["bg_input"], activebackground=C["border"],
            activeforeground=C["accent_soft"],
            relief="flat", bd=0, cursor="hand2", padx=14, pady=5,
            command=self._push_to_smartsheet,
        )
        self._btn_export.pack(side="left", padx=(0, 6))
        # Push starts disabled — only enabled when user switches to Selected View
        self._btn_export.config(
            state="disabled",
            text="⬇  Push unavailable in Full View",
            fg=C["text_dim"], cursor="arrow",
        )
        from tooltip import Tooltip as _TT
        _TT(self._btn_export, lambda: (
            "Push is only available in Selected View.\n"
            "Click  📋 Selected View  to switch."
            if self._btn_export["state"] == "disabled" else ""
        ))

        # ── View mode toggle ─────────────────────────────────
        tk.Frame(self._sub_top, bg=C["border"], width=1).pack(
            side="left", fill="y", pady=2, padx=(0, 6))

        self._btn_view_toggle = tk.Button(
            self._sub_top,
            text=f"🗂  Full View",
            font=f["btn"],
            fg=C["bg_card"], bg=C["accent"], activebackground=C["accent_soft"],
            activeforeground=C["bg_card"],
            relief="flat", bd=0, cursor="hand2", padx=14, pady=5,
            command=self._toggle_view_mode,
        )
        self._btn_view_toggle.pack(side="left", padx=(0, 4))

        self._lbl_pending = tk.Label(
            self._sub_top,
            text=f"⚠ {PENDING_FIELDS} fields TBD",
            font=f["small"], fg=C["warning"], bg=C["bg_card"],
            cursor="hand2",
        )
        self._lbl_pending.pack(side="left", padx=(2, 6))
        Tooltip(self._lbl_pending, self._pending_tooltip_text)

        self._btn_inspector = tk.Button(
            self._sub_top, text="🔎  Field Codes",
            font=f["btn"],
            fg=C["text_main"], bg=C["bg_input"],
            activebackground=C["border"], activeforeground=C["accent"],
            relief="flat", bd=0, cursor="hand2", padx=10, pady=5,
            command=self._show_field_inspector,
        )
        self._btn_inspector.pack(side="left", padx=(0, 6))

        tk.Frame(self._sub_top, bg=C["border"], width=1).pack(
            side="left", fill="y", pady=2, padx=(0, 6))

        # Re-push row by ID
        tk.Label(self._sub_top, text="Re-push ID:",
                 font=f["small"], fg=C["text_dim"], bg=C["bg_card"]
                 ).pack(side="left", padx=(6, 2))
        self._entry_repush = tk.Entry(
            self._sub_top, width=7, font=f["btn"],
            fg=C["accent"], bg=C["bg_input"],
            insertbackground=C["accent"], relief="flat", bd=4,
        )
        self._entry_repush.pack(side="left", padx=(0, 4))
        self._btn_repush = self._make_btn(
            "↩", C["bg_card"], C["text_dim"], C["accent"],
            self._repush_by_id, f)
        self._btn_repush.pack(side="left", padx=(0, 12))

        tk.Frame(self._sub_top, bg=C["border"], width=1).pack(side="left", fill="y", pady=2)

        # Info panel
        self._build_info_panel(f)

        # Search bar
        self._build_search_bar(sub_outer, f)

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # Table area
        self._table_frame = tk.Frame(self, bg=C["bg_dark"])
        self._table_frame.pack(fill="both", expand=True, padx=8, pady=6)

        self._table = TableWidget(
            parent=self._table_frame,
            config=self._cfg,
            on_row_double_click=self._on_row_double_click,
            on_sort=self._sort_by,
            on_render_complete=self._on_render_complete,
            on_render_progress=lambda msg: self._lbl_status.config(
                text=msg, fg=C["warning"]
            ),
        )

        # Status bar
        self._build_status_bar(f)

        self.bind("<Configure>", self._on_window_resize)
        self.after(100, self._tick)

    def _build_info_panel(self, f: dict):
        C = self._C
        self._info_frame = tk.Frame(self._sub_top, bg=C["bg_card"])
        self._info_frame.pack(side="left", padx=12)

        def stat_label(row, col, heading, font_key):
            tk.Label(self._info_frame, text=heading, font=f["small"],
                     fg=C["text_dim"], bg=C["bg_card"]).grid(row=row, column=col, sticky="w")
            lbl = tk.Label(self._info_frame, text="—",
                           font=f[font_key], fg=C["accent"], bg=C["bg_card"])
            lbl.grid(row=row, column=col + 1, sticky="w", padx=(3, 14))
            return lbl

        self._lbl_count         = stat_label(0, 0, "LOADED",        "badge")
        self._lbl_latest_id     = stat_label(0, 2, "LATEST ID",     "btn")
        self._lbl_kintone_total = stat_label(0, 4, "KINTONE TOTAL", "btn")

        tk.Label(self._info_frame, text="DELETED", font=f["small"],
                 fg=C["text_dim"], bg=C["bg_card"]).grid(row=1, column=0, sticky="w")
        self._lbl_deleted = tk.Label(self._info_frame, text="—",
                                     font=f["tiny"], fg=C["text_sub"], bg=C["bg_card"])
        self._lbl_deleted.grid(row=1, column=1, columnspan=4, sticky="w", padx=(3, 0))

        self._lbl_verify = tk.Label(self._info_frame, text="",
                                    font=f["tiny"], fg=C["text_sub"], bg=C["bg_card"])
        self._lbl_verify.grid(row=1, column=5, sticky="w", padx=(6, 0))

    def _build_search_bar(self, parent: tk.Frame, f: dict):
        C = self._C
        sub_bot = tk.Frame(parent, bg=C["bg_card"])
        sub_bot.pack(fill="x", padx=12, pady=(2, 6))
        sub_bot.columnconfigure(1, weight=1)

        tk.Label(sub_bot, text="🔍", font=("Segoe UI", 11),
                 fg=C["text_sub"], bg=C["bg_card"]).grid(row=0, column=0, padx=(0, 4))

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._on_search())
        self._ent_search = tk.Entry(
            sub_bot, textvariable=self._search_var,
            font=f["mono"], fg=C["text_main"],
            bg=C["bg_input"], insertbackground=C["accent"],
            relief="flat", bd=0,
        )
        self._ent_search.grid(row=0, column=1, sticky="ew", ipady=5, padx=(0, 8))

        self._lbl_filtered = tk.Label(sub_bot, text="",
                                      font=f["mono"], fg=C["text_sub"], bg=C["bg_card"])
        self._lbl_filtered.grid(row=0, column=2, padx=(4, 0))

    def _build_status_bar(self, f: dict):
        C = self._C
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")
        bar = tk.Frame(self, bg=C["bg_card"], height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self._lbl_status = tk.Label(bar, text="Connecting to Kintone…",
                                    font=f["mono"], fg=C["text_sub"], bg=C["bg_card"])
        self._lbl_status.pack(side="left", padx=14)

        Tooltip(self._lbl_status, lambda: self._col_tooltip_text)

        self._lbl_endpoint = tk.Label(
            bar,
            text=f"https://{self._cfg.kintone_subdomain}.kintone.com  •  App {self._cfg.kintone_app_id}",
            font=f["mono"], fg=C["text_dim"], bg=C["bg_card"],
        )
        self._lbl_endpoint.pack(side="right", padx=14)

    # ── Button factory ────────────────────────────────────────
    def _make_btn(self, text, fg, bg, abg, cmd, f) -> tk.Button:
        return tk.Button(
            self._sub_top, text=text, font=f["btn"],
            fg=fg, bg=bg, activebackground=abg, activeforeground=fg,
            relief="flat", bd=0, cursor="hand2", padx=14, pady=5, command=cmd,
        )

    # ── UI lock / unlock ──────────────────────────────────────
    def _set_ui_busy(self, label: str = "Working…"):
        """Disable all interactive controls while an operation is running."""
        C = self._C
        for btn in (
            self._btn_refresh, self._btn_order,
            self._btn_export,  self._btn_view_toggle,
            self._btn_repush,  self._btn_inspector,
        ):
            try:
                btn.config(state="disabled", cursor="watch")
            except Exception:
                pass
        try:
            self._ent_search.config(state="disabled")
            self._entry_repush.config(state="disabled")
        except Exception:
            pass
        self._lbl_status.config(text=f"⏳  {label}", fg=C["warning"])

    def _set_ui_ready(self):
        """Re-enable all controls after an operation completes."""
        C = self._C
        for btn in (
            self._btn_refresh, self._btn_order, self._btn_view_toggle,
            self._btn_inspector, self._btn_repush,
        ):
            try:
                btn.config(state="normal", cursor="hand2")
            except Exception:
                pass
        try:
            self._ent_search.config(state="normal")
            self._entry_repush.config(state="normal")
        except Exception:
            pass
        # Push button state depends on view mode
        if self._view_mode == "selected":
            self._btn_export.config(
                state="normal", text="⬇  PUSH TO SMARTSHEET",
                bg=C["bg_input"], fg=C["accent"], cursor="hand2",
            )
        else:
            self._btn_export.config(
                state="disabled", text="⬇  Push unavailable in Full View",
                fg=C["text_dim"], cursor="arrow",
            )

    # ═════════════════════════════════════════
    #  RESPONSIVE  RESIZE
    # ═════════════════════════════════════════
    def _on_window_resize(self, event):
        if event.widget is not self:
            return
        w = event.width
        if FontManager.tier(self._last_width) != FontManager.tier(w):
            self._apply_fonts(w)
        self._last_width = w

        if hasattr(self._table, "_tree") and self._table._tree:
            tw = self._table._tree.winfo_width()
            if tw > 100:
                self._table.resize_columns(self._active_fields(), tw)

        if hasattr(self, "_lbl_deleted"):
            if w < 1050:
                self._lbl_deleted.grid_remove()
                self._lbl_verify.grid_remove()
            else:
                self._lbl_deleted.grid()
                self._lbl_verify.grid()

        if hasattr(self, "_btn_export"):
            self._btn_export.config(
                text="⬇  EXPORT" if w < 1100 else "⬇  PUSH TO SMARTSHEET"
            )

    def _apply_fonts(self, width: int):
        f = FontManager.scale(width)
        pairs = [
            (self._lbl_title,         "title"),
            (self._lbl_time,          "mono"),
            (self._lbl_status,        "mono"),
            (self._lbl_endpoint,      "mono"),
            (self._btn_refresh,       "btn"),
            (self._btn_order,         "btn"),
            (self._btn_export,        "btn"),
            (self._lbl_count,         "badge"),
            (self._lbl_latest_id,     "btn"),
            (self._lbl_kintone_total, "btn"),
            (self._lbl_deleted,       "tiny"),
            (self._lbl_verify,        "tiny"),
            (self._lbl_filtered,      "mono"),
            (self._ent_search,        "mono"),
        ]
        for widget, key in pairs:
            try:
                if widget.winfo_exists():
                    widget.config(font=f[key])
            except Exception:
                pass
        self._table.refresh_style(f)

    # ═════════════════════════════════════════
    #  FETCH  RECORDS
    # ═════════════════════════════════════════
    def _start_fetch(self):
        self._set_ui_busy("Fetching data from Kintone…")
        self._btn_refresh.config(text="↺  Loading…")
        self._table.show_loading()
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        C = self._C
        try:
            records, fields = self._kintone_api.fetch_all_records(
                progress_cb=lambda msg: self.after(
                    0, lambda m=msg: self._lbl_status.config(text=m, fg=C["text_sub"])
                )
            )
            total = self._kintone_api.fetch_record_count()
            self.after(0, lambda r=records, f=fields, k=total:
                       self._on_fetch_success(r, f, k))
        except Exception as e:
            err = str(e)
            self.after(0, lambda e=err: self._on_fetch_error(e))

    def _on_fetch_success(self, records: list, fields: list, kintone_total: Optional[int]):
        self._table.stop_loading()
        records = RecordProcessor.order_by_id(records, self._date_desc)
        self._all_records = records

        if self._field_order:
            ordered = [f for f in self._field_order if f in fields]
            pinned  = [f for f in fields if f not in ordered]
            fields  = pinned + ordered
        self._field_codes = fields

        # Render using view-aware helpers
        active = self._active_fields()
        self._table.render(records, active, self._human_col_mapped)
        self._update_info_panel(records, kintone_total)
        self._btn_refresh.config(text="↺  Refresh")
        self._set_ui_ready()
        # Sync toggle button label with actual column count
        from field_mapping import TOTAL_FIELDS, CONFIRMED_CODES, PENDING_FIELDS
        self._btn_view_toggle.config(
            text=f"🗂  Full View  ({len(fields)} cols)"
        )
        self._lbl_pending.config(
            text=f"⚠ {PENDING_FIELDS} TBD  |  {CONFIRMED_CODES}/{TOTAL_FIELDS} mapped"
        )

    def _on_fetch_error(self, err: str):
        self._table.stop_loading()
        self._table.show_error(err)
        self._lbl_status.config(text=f"Error: {err[:120]}", fg=self._C["danger"])
        self._set_ui_ready()
        self._btn_refresh.config(text="↺  Retry")

    # ═════════════════════════════════════════
    #  INFO  PANEL  UPDATE
    # ═════════════════════════════════════════
    def _update_info_panel(self, records: list, kintone_total: Optional[int]):
        C         = self._C
        all_ids   = [RecordProcessor.cell_value(r, "$id") for r in records
                     if RecordProcessor.cell_value(r, "$id")]
        latest_id = max(all_ids, key=lambda x: x.zfill(10)) if all_ids else "?"
        latest_n  = int(latest_id) if latest_id != "?" else 0
        count     = len(records)

        self._lbl_count.config(text=f"{count:,}")
        self._lbl_latest_id.config(text=f"#{latest_id}")

        if kintone_total is not None:
            match = count == kintone_total
            self._lbl_kintone_total.config(
                text=f"{kintone_total:,}",
                fg=C["success"] if match else C["danger"],
            )
            deleted = latest_n - kintone_total
            self._lbl_deleted.config(
                text=(f"{deleted:,} IDs  "
                      f"(IDs issued: {latest_n:,}  −  existing: {kintone_total:,}  =  {deleted:,} deleted)"),
                fg=C["text_sub"],
            )
            if match:
                self._lbl_count.config(fg=C["success"])
                self._lbl_verify.config(
                    text=f"✓  All {kintone_total:,} records loaded", fg=C["success"])
            else:
                diff      = abs(kintone_total - count)
                direction = "added" if kintone_total > count else "deleted"
                self._lbl_count.config(fg=C["danger"])
                self._lbl_verify.config(
                    text=f"⚠  {diff:,} records {direction} since last refresh — click ↺",
                    fg=C["danger"],
                )
        else:
            self._lbl_kintone_total.config(text="unavailable", fg=C["warning"])
            self._lbl_deleted.config(
                text="could not verify — check API token permissions", fg=C["warning"])
            self._lbl_count.config(fg=C["accent"])
            self._lbl_verify.config(text="", fg=C["text_sub"])

        self._lbl_status.config(
            text=(f"✓  {count:,} records  •  latest ID #{latest_id}  •  "
                  f"{datetime.now().strftime('%H:%M:%S')}"),
            fg=C["success"],
        )

    # ═════════════════════════════════════════
    #  TABLE  CALLBACKS
    # ═════════════════════════════════════════
    def _on_render_complete(self, records: list, fields: list):
        C                  = self._C
        kintone_total_cols = len(self._field_labels)
        kintone_data_cols  = self._kintone_api.count_data_fields(self._field_labels)
        viewer_cols        = len(fields)

        type_labels = {
            "CALC": "CALC / formula", "REFERENCE_TABLE": "REFERENCE_TABLE",
            "LABEL": "LABEL", "HR": "HR (divider)", "SPACER": "SPACER",
            "CATEGORY": "CATEGORY", "STATUS": "STATUS",
            "STATUS_ASSIGNEE": "STATUS_ASSIGNEE",
        }
        type_counts: dict = {}
        for info in self._field_labels.values():
            t = info.get("type", "")
            if t in self._kintone_api.NON_DATA_TYPES:
                type_counts[t] = type_counts.get(t, 0) + 1

        lines = [
            f"  Kintone form fields   {kintone_total_cols}",
            f"  ├─ Data fields        {kintone_data_cols}   (shown in viewer)",
        ]
        items = list(type_counts.items())
        for i, (t, c) in enumerate(items):
            prefix = "└─" if i == len(items) - 1 else "├─"
            lines.append(f"  {prefix} {type_labels.get(t, t):<22} {c}")
        lines += [
            f"  {'─' * 40}",
            f"  Viewer columns        {viewer_cols}  ✓  matches data fields",
            "", "  ℹ  Non-data fields are excluded from the",
            "     count — no data is missing.",
        ]
        self._col_tooltip_text = "\n".join(lines)

        self._lbl_status.config(
            text=(f"✓  {len(records):,} records  •  {viewer_cols} cols  •  "
                  f"{datetime.now().strftime('%H:%M:%S')}  (hover for column breakdown)"),
            fg=C["success"],
        )
        self._lbl_filtered.config(
            text=f"Showing {len(records):,}"
            if len(records) != len(self._all_records) else ""
        )

    # ═════════════════════════════════════════
    #  HELPERS
    # ═════════════════════════════════════════
    def _human_col(self, code: str) -> str:
        return RecordProcessor.human_label(code, self._field_labels)

    def _filtered_records(self) -> list:
        return RecordProcessor.filter_records(self._all_records, self._filter_text)

    # ═════════════════════════════════════════
    #  SEARCH
    # ═════════════════════════════════════════
    def _on_search(self):
        self._filter_text = self._search_var.get().strip().lower()
        if not self._all_records:
            return
        filtered = self._filtered_records()
        self._table.repopulate(filtered, self._active_fields())
        self._lbl_filtered.config(
            text=(f"Showing {len(filtered):,} / {len(self._all_records):,}"
                  if filtered != self._all_records else "")
        )

    # ═════════════════════════════════════════
    #  SORT
    # ═════════════════════════════════════════
    def _sort_by(self, col: str):
        self._sort_rev = not self._sort_rev if self._sort_col == col else False
        self._sort_col = col
        data = RecordProcessor.sort_records(
            self._filtered_records(), col, reverse=self._sort_rev)
        active = self._active_fields()
        self._table.repopulate(data, active)
        self._table.update_sort_arrows(
            active, col, self._sort_rev, self._human_col_mapped)

    # ═════════════════════════════════════════
    #  ORDER  TOGGLE
    # ═════════════════════════════════════════
    def _toggle_order(self):
        if not self._all_records:
            return
        self._set_ui_busy("Sorting…")
        self._date_desc   = not self._date_desc
        self._all_records = RecordProcessor.order_by_id(self._all_records, self._date_desc)
        self._sort_col    = "$id"
        self._sort_rev    = self._date_desc
        self._btn_order.config(
            text="↕  Newest First" if self._date_desc else "↕  Oldest First")
        active = self._active_fields()
        self._table.repopulate(self._filtered_records(), active)
        self._table.update_sort_arrows(
            active, "$id", self._date_desc, self._human_col_mapped)
        self._set_ui_ready()

    # ═════════════════════════════════════════
    #  ROW  DETAIL  POPUP
    # ═════════════════════════════════════════
    def _on_row_double_click(self, _event):
        item = self._table.focused_item()
        if not item:
            return
        idx = int(item)
        rec = self._all_records[idx]
        C   = self._C

        popup = tk.Toplevel(self)
        popup.title(f"Record Detail  —  #{idx + 1}")
        popup.configure(bg=C["bg_dark"])
        popup.geometry("640x520")
        popup.resizable(True, True)

        hdr = tk.Frame(popup, bg=C["bg_card"], height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=f"  ◈  Record #{idx + 1}",
                 font=("Segoe UI", 14, "bold"),
                 fg=C["text_main"], bg=C["bg_card"]).pack(side="left", padx=16, pady=12)

        tk.Frame(popup, bg=C["border"], height=1).pack(fill="x")

        txt = tk.Text(
            popup, bg=C["bg_card"], fg=C["text_main"],
            font=("Consolas", 10), relief="flat", wrap="word",
            bd=0, padx=18, pady=12,
        )
        txt.pack(fill="both", expand=True, padx=12, pady=10)

        for code in self._field_codes:
            val   = RecordProcessor.cell_value(rec, code)
            label = self._human_col(code)
            txt.insert("end", f"{label:<24}", ("key",))
            txt.insert("end", f"{val}\n")

        txt.tag_configure("key", foreground=C["accent"], font=("Segoe UI", 9, "bold"))
        txt.config(state="disabled")

    # ═════════════════════════════════════════
    #  PUSH  TO  SMARTSHEET
    # ═════════════════════════════════════════
    def _push_to_smartsheet(self):
        """Show a pre-push confirmation popup before sending anything."""
        C = self._C
        if not self._all_records:
            self._lbl_status.config(text="No records to push.", fg=C["warning"])
            return
        self._set_ui_busy("Preparing push…")
        self._show_push_confirm()

    def _show_push_confirm(self):
        """
        Confirmation popup: shows exactly which columns will be sent to Smartsheet
        and in which view mode, so the user can verify before committing.
        """
        C      = self._C
        fields = self._active_fields()
        if not fields:
            self._lbl_status.config(
                text="No mapped fields found. Fill in field_mapping.py first.",
                fg=C["warning"])
            return

        desired = self._build_push_desired()   # [(kintone_code, ss_label), ...]
        mode    = "Selected View" if self._view_mode == "selected" else "Full View"

        popup = tk.Toplevel(self)
        popup.title("Confirm Push to Smartsheet")
        popup.configure(bg=C["bg_dark"])
        popup.geometry("700x560")
        popup.resizable(True, True)
        popup.grab_set()

        # ── Header ───────────────────────────────────────────────────────
        hdr = tk.Frame(popup, bg=C["accent"], height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  ⬆  Confirm Push to Smartsheet",
                 font=("Segoe UI", 13, "bold"),
                 fg="#FFFFFF", bg=C["accent"]).pack(side="left", padx=16, pady=14)
        tk.Label(hdr, text=f"Mode: {mode}",
                 font=("Segoe UI", 9), fg="#CCDDF8",
                 bg=C["accent"]).pack(side="right", padx=16)

        tk.Frame(popup, bg=C["border"], height=1).pack(fill="x")

        # ── Summary strip ────────────────────────────────────────────────
        strip = tk.Frame(popup, bg=C["bg_input"], padx=16, pady=10)
        strip.pack(fill="x")
        strip.columnconfigure(1, weight=1)
        strip.columnconfigure(3, weight=1)

        def stat(row, col, heading, value, color):
            tk.Label(strip, text=heading, font=("Segoe UI", 8),
                     fg=C["text_dim"], bg=C["bg_input"]
                     ).grid(row=row, column=col, sticky="w")
            tk.Label(strip, text=value, font=("Segoe UI", 11, "bold"),
                     fg=color, bg=C["bg_input"]
                     ).grid(row=row, column=col+1, sticky="w", padx=(4, 24))

        stat(0, 0, "RECORDS",  f"{len(self._all_records):,}", C["accent"])
        stat(0, 2, "COLUMNS",  f"{len(desired)}",             C["accent"])
        stat(1, 0, "SHEET ID", self._cfg.smartsheet_sheet_id, C["text_sub"])
        stat(1, 2, "VIEW MODE", mode,
             C["success"] if self._view_mode == "selected" else C["text_sub"])

        # Info note about smart insert/update behaviour
        tk.Label(
            strip,
            text=(
                "ℹ  New records → INSERT   •   "
                "Existing records → UPDATE missing columns only   •   "
                "No duplicates created"
            ),
            font=("Segoe UI", 8), fg=C["accent"], bg=C["bg_input"],
        ).grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))

        tk.Frame(popup, bg=C["border"], height=1).pack(fill="x")

        # ── Info label ───────────────────────────────────────────────────
        tk.Label(
            popup,
            text="The following columns will be created/matched in Smartsheet:",
            font=("Segoe UI", 9), fg=C["text_sub"], bg=C["bg_dark"],
        ).pack(anchor="w", padx=16, pady=(10, 4))

        # ── Column mapping table ─────────────────────────────────────────
        tbl_frame = tk.Frame(popup, bg=C["bg_dark"])
        tbl_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        vsb = ttk.Scrollbar(tbl_frame, orient="vertical", style="KV.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")

        cols = ("#", "kintone", "arrow", "smartsheet")
        tree = ttk.Treeview(tbl_frame, columns=cols, show="headings",
                            style="KV.Treeview", yscrollcommand=vsb.set,
                            selectmode="none", height=14)
        tree.pack(fill="both", expand=True)
        vsb.config(command=tree.yview)

        tree.heading("#",          text=" #")
        tree.heading("kintone",    text="  Kintone Column (source)")
        tree.heading("arrow",      text="")
        tree.heading("smartsheet", text="  Smartsheet Column (destination)")

        tree.column("#",          width=36,  minwidth=30,  anchor="center")
        tree.column("kintone",    width=260, minwidth=120, anchor="w")
        tree.column("arrow",      width=36,  minwidth=30,  anchor="center")
        tree.column("smartsheet", width=280, minwidth=120, anchor="w")

        tree.tag_configure("confirmed", foreground=C["success"],  background="#F0FBF4")
        tree.tag_configure("pending",   foreground=C["warning"],  background="#FFFBF0")

        for i, (code, ss_label) in enumerate(desired, 1):
            kintone_label = RecordProcessor.human_label(code, self._field_labels)
            is_confirmed  = ss_label != kintone_label  # label was remapped
            tag = "confirmed" if is_confirmed else "pending"
            tree.insert("", "end",
                        values=(i, f"  {kintone_label}", "→", f"  {ss_label}"),
                        tags=(tag,))

        # ── Legend ───────────────────────────────────────────────────────
        leg = tk.Frame(popup, bg=C["bg_dark"], padx=16)
        leg.pack(fill="x", pady=(0, 4))
        for symbol, color, text in [
            ("■", C["success"], "Column name remapped to Smartsheet label"),
            ("■", C["warning"], "Column name unchanged (auto-label)"),
        ]:
            tk.Label(leg, text=symbol, font=("Segoe UI", 10),
                     fg=color, bg=C["bg_dark"]).pack(side="left", padx=(0, 3))
            tk.Label(leg, text=text,   font=("Segoe UI", 8),
                     fg=C["text_dim"], bg=C["bg_dark"]).pack(side="left", padx=(0, 14))

        tk.Frame(popup, bg=C["border"], height=1).pack(fill="x")

        # ── Action buttons ───────────────────────────────────────────────
        btn_bar = tk.Frame(popup, bg=C["bg_card"], height=50)
        btn_bar.pack(fill="x")
        btn_bar.pack_propagate(False)

        def confirm():
            popup.destroy()
            self._btn_export.config(state="disabled", text="⬆  Pushing…")
            self._lbl_status.config(text="Connecting to Smartsheet…", fg=C["warning"])
            threading.Thread(target=self._smartsheet_worker, daemon=True).start()

        def cancel():
            popup.destroy()
            self._set_ui_ready()

        tk.Button(
            btn_bar, text="  Cancel  ",
            font=("Segoe UI", 10), fg=C["text_sub"], bg=C["bg_input"],
            activebackground=C["border"], activeforeground=C["text_main"],
            relief="flat", bd=0, cursor="hand2",
            command=cancel,
        ).pack(side="right", padx=(8, 16), pady=10)

        tk.Button(
            btn_bar, text=f"  ⬆  Push {len(desired)} columns  →  Smartsheet  ",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF", bg=C["accent"],
            activebackground=C["accent_soft"], activeforeground="#FFFFFF",
            relief="flat", bd=0, cursor="hand2",
            command=confirm,
        ).pack(side="right", pady=10)

    def _do_push(self):
        """Fire the actual push — called after user confirms."""
        C = self._C
        self._btn_export.config(state="disabled", text="⬆  Pushing…")
        self._lbl_status.config(text="Connecting to Smartsheet…", fg=C["warning"])
        threading.Thread(target=self._smartsheet_worker, daemon=True).start()

    def _smartsheet_worker(self):
        """
        Smart push — respects data already in Smartsheet regardless of view mode:

          NEW records      → INSERT  (POST)  with all current view columns
          EXISTING records → UPDATE  (PUT)   filling in any columns not yet pushed
                             (e.g. Full View fills missing cols from a prior
                              Selected View push, and vice versa — no duplicates)
        """
        C = self._C

        def ui(fn): self.after(0, fn)

        try:
            # ── Step 1: Sync columns ──────────────────────────
            ui(lambda: self._lbl_status.config(
                text="Connecting to Smartsheet…", fg=C["warning"]))
            sheet_data    = self._ss_api.fetch_sheet()
            existing_cols = sheet_data.get("columns", [])

            ui(lambda: self._lbl_status.config(text="Checking columns…", fg=C["warning"]))
            desired = self._build_push_desired()

            # Always ensure ID column exists as dedup anchor
            has_id = any(c == "$id" for c, _ in desired)
            if not has_id:
                desired = [("$id", "ID")] + list(desired)

            col_map, missing_cols = self._ss_api.sync_columns(
                desired=desired,
                existing_cols=existing_cols,
                progress_cb=lambda msg: ui(
                    lambda m=msg: self._lbl_status.config(text=m, fg=C["warning"])
                ),
            )

            # Warn user if any columns were rejected by Smartsheet
            if missing_cols:
                n_miss = len(missing_cols)
                n_ok   = len(col_map)
                n_want = len(desired)
                names  = ", ".join(f'"{l}"' for _, l in missing_cols[:5])
                suffix = f" +{n_miss-5} more" if n_miss > 5 else ""
                ui(lambda msg=f"⚠  {n_miss} column(s) rejected by Smartsheet "
                              f"({n_ok}/{n_want} created): {names}{suffix}. "
                              f"See smartsheet_debug.log":
                    self._lbl_status.config(text=msg, fg=C["warning"])
                )
                import time; time.sleep(3)   # pause so user can read warning

            # ── Step 2: Fetch existing row map {kintone_id → ss_row_id} ──
            ui(lambda: self._lbl_status.config(
                text="Scanning existing Smartsheet rows…", fg=C["warning"]))
            row_map = self._ss_api.fetch_existing_row_map(
                col_map, "$id",
                progress_cb=lambda msg: ui(
                    lambda m=msg: self._lbl_status.config(text=m, fg=C["warning"])
                ),
            )
            existing_ids = set(row_map.keys())

            # ── Step 3: Split records into INSERT vs UPDATE ───
            push_fields   = self._active_fields()
            # Ensure $id is always included in the payload for the anchor column
            if "$id" not in push_fields:
                push_fields = ["$id"] + push_fields

            insert_records = []
            update_records = []

            for rec in self._all_records:
                raw_id = RecordProcessor.cell_value(rec, "$id")
                if not raw_id.isdigit():
                    continue
                kid = int(raw_id)
                if kid in existing_ids:
                    update_records.append((kid, rec))
                else:
                    insert_records.append(rec)

            n_insert = len(insert_records)
            n_update = len(update_records)

            ui(lambda i=n_insert, u=n_update: self._lbl_status.config(
                text=f"Found {u:,} existing rows to update  •  {i:,} new rows to insert…",
                fg=C["warning"],
            ))

            if not insert_records and not update_records:
                ts = datetime.now().strftime("%H:%M:%S")
                ui(lambda: (
                    self._lbl_status.config(
                        text=f"✓  Smartsheet already up to date  •  {ts}",
                        fg=C["success"]),
                    self._btn_export.config(state="normal", text="⬇  PUSH TO SMARTSHEET"),
                ))
                return

            # ── Step 4: INSERT new records (atomic with rollback) ──
            if insert_records:
                rows_to_insert = self._ss_api.build_rows_payload(
                    records=insert_records,
                    field_codes=push_fields,
                    col_map=col_map,
                    cell_value_fn=RecordProcessor.cell_value,
                )
                self._ss_api.push_rows_atomic(
                    rows_to_insert,
                    progress_cb=lambda msg: ui(
                        lambda m=msg: self._lbl_status.config(text=m, fg=C["warning"])
                    ),
                )

            # ── Step 5: UPDATE existing records (fill missing cols) ──
            if update_records:
                rows_to_update = []
                for kid, rec in update_records:
                    ss_row_id = row_map[kid]
                    cells     = []
                    seen      = set()
                    for code in push_fields:
                        col_id = col_map.get(code)
                        if col_id is None or col_id in seen:
                            continue
                        seen.add(col_id)
                        cells.append({
                            "columnId": int(col_id),
                            "value":    RecordProcessor.cell_value(rec, code),
                        })
                    if cells:
                        rows_to_update.append({"id": int(ss_row_id), "cells": cells})

                self._ss_api.update_rows(
                    rows_to_update,
                    progress_cb=lambda msg: ui(
                        lambda m=msg: self._lbl_status.config(text=m, fg=C["warning"])
                    ),
                )

            ts = datetime.now().strftime("%H:%M:%S")
            ui(lambda i=n_insert, u=n_update: (
                self._lbl_status.config(
                    text=(f"✓  Done  •  {i:,} inserted  •  {u:,} updated  •  {ts}"),
                    fg=C["success"]),
                self._set_ui_ready(),
            ))

        except Exception as e:
            err = str(e)
            ui(lambda err=err: (
                self._lbl_status.config(
                    text="✗  Push failed — See error popup",
                    fg=C["danger"]),
                self._set_ui_ready(),
                self._show_error_popup(err),
            ))

    # ═════════════════════════════════════════
    #  REPUSH  SINGLE  ROW  BY  ID
    # ═════════════════════════════════════════
    def _repush_by_id(self):
        C   = self._C
        raw = self._entry_repush.get().strip()
        if not raw.isdigit():
            self._lbl_status.config(
                text="Re-push: enter a valid numeric record ID.", fg=C["warning"])
            return

        target_id = int(raw)
        match_rec = next(
            (r for r in self._all_records
             if RecordProcessor.cell_value(r, "$id") == str(target_id)
             or RecordProcessor.cell_value(r, "Record_number") == str(target_id)),
            None,
        )
        if match_rec is None:
            self._lbl_status.config(
                text=f"Re-push: ID {target_id} not found. Try refreshing first.",
                fg=C["danger"],
            )
            return

        self._set_ui_busy(f"Re-pushing record ID {target_id}…")
        threading.Thread(
            target=self._repush_worker, args=(match_rec, target_id), daemon=True
        ).start()

    def _repush_worker(self, rec: dict, target_id: int):
        """
        Re-push a single record by ID.
        Fast path: check existence first using only the ID column.
          • Already exists → skip, show "already in Smartsheet" immediately.
          • Not found      → insert, show "added successfully".
        No update on re-push — the main Push button handles updates.
        """
        C = self._C

        def ui(fn): self.after(0, fn)

        try:
            push_fields = self._active_fields()
            if "$id" not in push_fields:
                push_fields = ["$id"] + push_fields

            desired = [
                (code, RecordProcessor.ss_column_name(self._human_col_mapped(code)))
                for code in push_fields
            ]
            col_map, _ = self._ss_api.sync_columns(
                desired=desired,
                existing_cols=self._ss_api.fetch_columns(),
            )
            if not col_map:
                raise RuntimeError("No columns matched — cannot push row.")

            # ── Fast existence check: fetch only the ID column ────────────────
            existing_ids = self._ss_api.fetch_existing_ids(col_map, "$id")

            if target_id in existing_ids:
                # Already in Smartsheet — nothing to do
                ui(lambda: (
                    self._lbl_status.config(
                        text=f"ℹ  Record ID {target_id} already exists in Smartsheet — skipped.",
                        fg=C["text_sub"]),
                    self._set_ui_ready(),
                    self._entry_repush.delete(0, "end"),
                ))
                return

            # ── Not found → INSERT ────────────────────────────────────────────
            rows = self._ss_api.build_rows_payload(
                records=[rec], field_codes=push_fields,
                col_map=col_map, cell_value_fn=RecordProcessor.cell_value,
            )
            self._ss_api.push_rows_atomic(rows)

            ui(lambda: (
                self._lbl_status.config(
                    text=f"✓  Record ID {target_id} added to Smartsheet successfully.",
                    fg=C["success"]),
                self._set_ui_ready(),
                self._entry_repush.delete(0, "end"),
            ))

        except Exception as e:
            err = str(e)
            ui(lambda err=err: (
                self._lbl_status.config(
                    text=f"Re-push failed: {err[:120]}", fg=C["danger"]),
                self._set_ui_ready(),
            ))

    # ═════════════════════════════════════════
    #  ERROR  POPUP
    # ═════════════════════════════════════════
    def _show_error_popup(self, message: str):
        C     = self._C
        popup = tk.Toplevel(self)
        popup.title("Push Failed")
        popup.configure(bg=C["bg_dark"])
        popup.geometry("580x320")
        popup.resizable(True, True)
        popup.grab_set()

        hdr = tk.Frame(popup, bg=C["danger"], height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  ✕  Smartsheet Push Failed",
                 font=("Segoe UI", 13, "bold"),
                 fg="#FFFFFF", bg=C["danger"]).pack(side="left", padx=16, pady=10)

        tk.Frame(popup, bg=C["border"], height=1).pack(fill="x")
        tk.Label(popup,
                 text="Smartsheet data has been restored. Full error details below:",
                 font=("Segoe UI", 9), fg=C["text_sub"], bg=C["bg_dark"]
                 ).pack(anchor="w", padx=16, pady=(10, 4))

        frame = tk.Frame(popup, bg=C["bg_dark"])
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        vsb = tk.Scrollbar(frame)
        vsb.pack(side="right", fill="y")
        txt = tk.Text(
            frame, bg=C["bg_card"], fg=C["danger"],
            font=("Consolas", 9), relief="flat", bd=0,
            wrap="word", padx=12, pady=10, yscrollcommand=vsb.set,
        )
        txt.pack(fill="both", expand=True)
        vsb.config(command=txt.yview)
        txt.insert("end", message)
        txt.config(state="disabled")

        tk.Frame(popup, bg=C["border"], height=1).pack(fill="x")
        btn_frame = tk.Frame(popup, bg=C["bg_card"], height=48)
        btn_frame.pack(fill="x")
        btn_frame.pack_propagate(False)
        tk.Button(
            btn_frame, text="  Close  ",
            font=("Segoe UI", 10, "bold"),
            fg=C["bg_card"], bg=C["danger"],
            activebackground=C["accent_soft"], activeforeground=C["bg_card"],
            relief="flat", bd=0, cursor="hand2",
            command=popup.destroy,
        ).pack(side="right", padx=16, pady=10)

    # ═════════════════════════════════════════
    #  CLOCK
    # ═════════════════════════════════════════
    def _tick(self):
        self._lbl_time.config(text=datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        self.after(1000, self._tick)
    # ═════════════════════════════════════════
    #  VIEW  MODE  (Full ↔ Selected)
    # ═════════════════════════════════════════
    def _toggle_view_mode(self):
        """Switch between Full View (all columns) and Selected View (mapped columns only)."""
        if not self._all_records:
            return
        self._view_mode = "selected" if self._view_mode == "full" else "full"
        self._apply_view_mode()

    def _apply_view_mode(self):
        """Re-render the table using the current view mode and update button labels."""
        C          = self._C
        fields     = self._active_fields()
        filtered   = RecordProcessor.filter_records(self._all_records, self._filter_text)

        from field_mapping import TOTAL_FIELDS, CONFIRMED_CODES, PENDING_FIELDS
        if self._view_mode == "selected":
            self._btn_view_toggle.config(
                text=f"📋  Selected View  ({len(fields)}/{CONFIRMED_CODES} matched)",
                fg=C["accent"], bg=C["bg_input"],
                activebackground=C["border"],
            )
            self._lbl_pending.config(
                text=f"⚠ {PENDING_FIELDS} TBD  |  {CONFIRMED_CODES}/{TOTAL_FIELDS} mapped"
            )
            self._lbl_status.config(
                text=(f"Selected View: {len(fields)} columns shown  •  "
                      f"{CONFIRMED_CODES}/{TOTAL_FIELDS} mapped  •  {PENDING_FIELDS} still TBD"),
                fg=C["warning"],
            )
            # Push only available in Selected View
            self._btn_export.config(
                state="normal",
                text="⬇  PUSH TO SMARTSHEET",
                bg=C["bg_input"], fg=C["accent"],
                cursor="hand2",
            )
        else:
            self._btn_view_toggle.config(
                text=f"🗂  Full View  ({len(self._field_codes)} cols)  — read only",
                fg=C["bg_card"], bg=C["accent"],
                activebackground=C["accent_soft"],
            )
            self._lbl_pending.config(
                text=f"⚠ {PENDING_FIELDS} TBD  |  {CONFIRMED_CODES}/{TOTAL_FIELDS} mapped"
            )
            # Disable push in Full View — read only
            self._btn_export.config(
                state="disabled",
                text="⬇  Push unavailable in Full View",
                bg=C["bg_input"], fg=C["text_dim"],
                cursor="arrow",
            )

        self._table.render(filtered, fields, self._human_col_mapped)

    # ─────────────────────────────────────────
    #  LABEL  NORMALIZER
    # ─────────────────────────────────────────
    @staticmethod
    def _norm(text: str) -> str:
        """
        Aggressive label normalizer — strips ALL whitespace and normalizes
        unicode so tiny differences never cause a miss:
          "AMD, SLT, …"  ==  "AMD, SLT,…"  (space before ellipsis)
          competitor’s    ==  competitor's               (curly vs straight quote)
          "Pitch ★"              ==  "Pitch"                     (trailing symbol)
          "Application:"             ==  "Application"                (trailing colon)
          "Signal "                  ==  "Signal"                     (trailing space)
        """
        import re as _re
        s = text.strip()
        # Convert unicode ellipsis variants to ...
        s = s.replace("…", "...").replace("⋯", "...")
        # Convert curly/smart quotes to straight
        s = s.replace("’", "'").replace("‘", "'")
        s = s.replace("”", '"').replace("“", '"')
        # Strip trailing punctuation / decorative symbols
        s = s.rstrip(":?!★☆●◆▶").strip()
        # Remove ALL whitespace so "AMD, SLT, ..." == "AMD, SLT,..."
        s = _re.sub(r"\s+", "", s)
        return s.lower()

    def _active_fields(self) -> list:
        """
        Return the field code list for the current view mode.
        Full view  → all loaded Kintone field codes.
        Selected   → codes matched to ACTIVE_MAP by normalized label,
                     in mapping-table order (preserves agreed column sequence).
        """
        if self._view_mode == "full":
            return self._field_codes

        # Build normalized-label → (original_label, code) map
        norm_to_code: dict[str, tuple] = {}
        for code in self._field_codes:
            lbl = RecordProcessor.human_label(code, self._field_labels)
            norm_to_code[self._norm(lbl)] = (lbl, code)

        # Walk ACTIVE_MAP in order; fuzzy-match each entry
        result       = []
        result_set   = set()
        for entry in ACTIVE_MAP:
            norm_key = self._norm(entry.kintone_label)
            match    = norm_to_code.get(norm_key)
            if match:
                _, code = match
                if code not in result_set:
                    result.append(code)
                    result_set.add(code)
        return result

    def _human_col_mapped(self, code: str) -> str:
        """
        Column label resolver for both view modes.
        Always returns the KINTONE display label — the viewer is a Kintone viewer.
        Smartsheet renaming only happens at push time inside _build_push_desired().
        """
        return RecordProcessor.human_label(code, self._field_labels)

    def _pending_tooltip_text(self) -> str:
        """Tooltip for the ⚠ TBD badge — lists every unresolved field."""
        lines = [
            f"  {PENDING_FIELDS} Kintone fields not yet identified  ({CONFIRMED_CODES}/{TOTAL_FIELDS} confirmed)",
            f"  {chr(9472) * 46}",
        ]
        for entry in FIELD_MAP:
            if entry.kintone_label == "":
                lines.append(f"  ????  →  {entry.smartsheet_label}")
        lines += ["", "  Edit field_mapping.py — set kintone_label for each ???? row."]
        return "\n".join(lines)

    # ═════════════════════════════════════════
    #  OVERRIDE  push to use mapping in
    #  selected-view mode
    # ═════════════════════════════════════════
    def _build_push_desired(self) -> list:
        """
        Build the (kintone_code, smartsheet_label) list for the Smartsheet push.
        Selected view  → curated Smartsheet labels from FIELD_MAP (matched by Kintone label).
        Full view      → auto-generated labels from Kintone field names.
        """
        fields = self._active_fields()
        return [
            (code, RecordProcessor.ss_column_name(self._human_col_mapped(code)))
            for code in fields
        ]
    # ═════════════════════════════════════════
    #  FIELD  CODE  INSPECTOR
    # ═════════════════════════════════════════
    def _show_field_inspector(self):
        """
        Popup that shows every Kintone field code loaded from the live app,
        its human label, its type, and whether it is already mapped in field_mapping.py.
        Copy the codes from here into field_mapping.py to fix the None entries.
        """
        C     = self._C
        popup = tk.Toplevel(self)
        popup.title("Field Code Inspector  —  copy codes into field_mapping.py")
        popup.configure(bg=C["bg_dark"])
        popup.geometry("860x580")
        popup.resizable(True, True)

        # ── Header ───────────────────────────────────────────
        hdr = tk.Frame(popup, bg=C["accent"], height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr, text="  🔎  Field Code Inspector",
            font=("Segoe UI", 13, "bold"), fg="#FFFFFF", bg=C["accent"],
        ).pack(side="left", padx=16, pady=12)

        # Count fields whose normalized label matches any ACTIVE_MAP entry
        active_norms = {self._norm(e.kintone_label) for e in ACTIVE_MAP}
        mapped_count = sum(
            1 for code in self._field_codes
            if self._norm(RecordProcessor.human_label(code, self._field_labels)) in active_norms
        )
        tk.Label(
            hdr,
            text=f"{mapped_count} / {len(self._field_codes)} fields mapped  •  copy codes into field_mapping.py",
            font=("Segoe UI", 9), fg="#CCDDF8", bg=C["accent"],
        ).pack(side="right", padx=16)

        tk.Frame(popup, bg=C["border"], height=1).pack(fill="x")

        # ── Legend ───────────────────────────────────────────
        leg = tk.Frame(popup, bg=C["bg_card"], padx=14, pady=6)
        leg.pack(fill="x")
        for symbol, color, meaning in [
            ("✓", C["success"], "Already mapped in field_mapping.py"),
            ("?", C["warning"], "In field_mapping.py but code was None (needs fixing)"),
            ("—", C["text_dim"], "Not in field_mapping.py at all"),
        ]:
            tk.Label(leg, text=f"  {symbol}  {meaning}",
                     font=("Segoe UI", 9), fg=color, bg=C["bg_card"]).pack(side="left", padx=8)

        tk.Frame(popup, bg=C["border"], height=1).pack(fill="x")

        # ── Table ─────────────────────────────────────────────
        frame = tk.Frame(popup, bg=C["bg_dark"])
        frame.pack(fill="both", expand=True, padx=10, pady=8)

        vsb = ttk.Scrollbar(frame, orient="vertical",   style="KV.Vertical.TScrollbar")
        hsb = ttk.Scrollbar(frame, orient="horizontal", style="KV.Horizontal.TScrollbar")
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")

        cols = ("status", "kintone_code", "kintone_label", "field_type", "smartsheet_label")
        tree = ttk.Treeview(
            frame, columns=cols, show="headings",
            style="KV.Treeview", yscrollcommand=vsb.set,
            xscrollcommand=hsb.set, selectmode="browse",
        )
        tree.pack(fill="both", expand=True)
        vsb.config(command=tree.yview)
        hsb.config(command=tree.xview)

        tree.heading("status",           text="  Status")
        tree.heading("kintone_code",     text="  Kintone Field Code  ← copy this")
        tree.heading("kintone_label",    text="  Kintone Label")
        tree.heading("field_type",       text="  Type")
        tree.heading("smartsheet_label", text="  Smartsheet Column Target")

        tree.column("status",           width=60,  minwidth=50,  anchor="center")
        tree.column("kintone_code",     width=240, minwidth=120, anchor="w")
        tree.column("kintone_label",    width=200, minwidth=100, anchor="w")
        tree.column("field_type",       width=140, minwidth=80,  anchor="w")
        tree.column("smartsheet_label", width=220, minwidth=100, anchor="w")

        # Row tag colours
        tree.tag_configure("mapped",   foreground=C["success"],  background="#F0FBF4")
        tree.tag_configure("pending",  foreground=C["warning"],  background="#FFFBF0")
        tree.tag_configure("unmapped", foreground=C["text_dim"], background=C["bg_row_odd"])

        # Build lookup: kintone_label → smartsheet_label for all active entries
        # and set of SS labels still pending (kintone_label == "")
        pending_ss: set[str] = {e.smartsheet_label for e in FIELD_MAP if e.kintone_label == ""}

        # Build normalized-label → ss_label lookup for inspector
        norm_to_ss: dict[str, str] = {
            self._norm(e.kintone_label): e.smartsheet_label
            for e in ACTIVE_MAP
        }

        for code in self._field_codes:
            label    = RecordProcessor.human_label(code, self._field_labels)
            ftype    = self._field_labels.get(code, {}).get("type", "—")
            norm_lbl = self._norm(label)

            if norm_lbl in norm_to_ss:
                ss_label = norm_to_ss[norm_lbl]
                status   = "✓  mapped"
                tag      = "mapped"
                # Highlight where the label was changed
                if label.strip() != ss_label.strip():
                    status = "✓  remapped"
            else:
                status   = "—  not mapped"
                ss_label = ""
                tag      = "unmapped"

            tree.insert("", "end", values=(status, code, label, ftype, ss_label), tags=(tag,))

        # ── Copy on click ─────────────────────────────────────
        def on_select(_event):
            item = tree.focus()
            if not item:
                return
            code = tree.item(item, "values")[1]
            popup.clipboard_clear()
            popup.clipboard_append(code)
            lbl_copy.config(text=f'✓  Copied:  "{code}"', fg=C["success"])

        tree.bind("<<TreeviewSelect>>", on_select)

        # ── Footer ───────────────────────────────────────────
        tk.Frame(popup, bg=C["border"], height=1).pack(fill="x")
        foot = tk.Frame(popup, bg=C["bg_card"], height=38)
        foot.pack(fill="x")
        foot.pack_propagate(False)

        lbl_copy = tk.Label(
            foot, text="Click any row to copy its Kintone field code to clipboard",
            font=("Segoe UI", 9), fg=C["text_dim"], bg=C["bg_card"],
        )
        lbl_copy.pack(side="left", padx=14, pady=8)

        tk.Button(
            foot, text="  Close  ", font=("Segoe UI", 9, "bold"),
            fg=C["bg_card"], bg=C["accent"],
            activebackground=C["accent_soft"], activeforeground=C["bg_card"],
            relief="flat", bd=0, cursor="hand2",
            command=popup.destroy,
        ).pack(side="right", padx=14, pady=6)