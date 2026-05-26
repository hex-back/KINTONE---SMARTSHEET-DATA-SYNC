"""
config.py
─────────
Single source of truth for every constant in the application.
Edit credentials here — nothing else needs to change.
"""

from dataclasses import dataclass, field


@dataclass
class AppConfig:
    # ── Kintone ──────────────────────────────────────────────
    kintone_subdomain:  str = "YOUR_SUBDOMAIN_HERE"   # e.g. "mycompany" → mycompany.kintone.com
    kintone_app_id:     str = "YOUR_APP_ID_HERE"      # found in the Kintone app URL → /k/4/ = "4"
    kintone_api_token:  str = "YOUR_KINTONE_API_TOKEN_HERE"  # App Settings → API Token
    kintone_fetch_size: int = 500                     # max 500 — safe to leave as-is

    # ── Smartsheet ───────────────────────────────────────────
    smartsheet_api_token: str = "YOUR_SMARTSHEET_API_TOKEN_HERE"  # Account → API Access
    smartsheet_sheet_id:  str = "YOUR_SHEET_ID_HERE"  # found in the Smartsheet URL

    # ── Palette ───────────────────────────────────────────────
    colors: dict = field(default_factory=lambda: {
        "bg_dark":      "#F0F5FB",
        "bg_card":      "#FFFFFF",
        "bg_input":     "#EBF1FA",
        "bg_row_even":  "#FFFFFF",
        "bg_row_odd":   "#F4F8FD",
        "accent":       "#1A65C8",
        "accent_soft":  "#1450A0",
        "accent_glow":  "#2176E0",
        "text_main":    "#1B2532",
        "text_sub":     "#4E6080",
        "text_dim":     "#9EB2CC",
        "border":       "#D4E1F1",
        "danger":       "#D93025",
        "warning":      "#C96A00",
        "success":      "#1E7A40",
        "header_bg":    "#FFFFFF",
        "selection":    "#C4DAFB",
    })

    # ── Static fonts ──────────────────────────────────────────
    fonts: dict = field(default_factory=lambda: {
        "title":   ("Segoe UI", 18, "bold"),
        "sub":     ("Segoe UI", 10),
        "mono":    ("Consolas", 10),
        "badge":   ("Segoe UI", 14, "bold"),
        "btn":     ("Segoe UI", 10, "bold"),
        "table_h": ("Segoe UI",  9, "bold"),
        "table":   ("Segoe UI",  9),
    })

    @property
    def kintone_base_url(self) -> str:
        return f"https://{self.kintone_subdomain}.kintone.com"

    @property
    def smartsheet_base_url(self) -> str:
        return f"https://api.smartsheet.com/2.0/sheets/{self.smartsheet_sheet_id}"
