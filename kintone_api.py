"""
kintone_api.py
──────────────
All Kintone REST API interactions.
Receives AppConfig — never imports from the GUI layer.
"""

from typing import Callable, Optional

import requests

from config import AppConfig
from record_processor import RecordProcessor


class KintoneAPI:

    NON_DATA_TYPES = frozenset({
        "CALC", "REFERENCE_TABLE", "LABEL",
        "HR", "SPACER", "CATEGORY", "STATUS", "STATUS_ASSIGNEE",
    })

    def __init__(self, config: AppConfig):
        self._cfg = config

    # ── Private helpers ───────────────────────────────────────
    def _headers(self) -> dict:
        return {
            "X-Cybozu-API-Token": self._cfg.kintone_api_token,
            "Content-Type": "application/json",
        }

    def _get_headers(self) -> dict:
        return {"X-Cybozu-API-Token": self._cfg.kintone_api_token}

    # ── Public methods ────────────────────────────────────────
    def fetch_all_records(self, progress_cb: Optional[Callable] = None) -> tuple:
        """
        Fetch every record (cursor API → offset fallback).
        Returns (records: list, field_codes: list).
        """
        cursor_url  = f"{self._cfg.kintone_base_url}/k/v1/records/cursor.json"
        records_url = f"{self._cfg.kintone_base_url}/k/v1/records.json"
        app_id      = int(self._cfg.kintone_app_id)
        size        = max(1, min(self._cfg.kintone_fetch_size, 500))

        all_records    = []
        cursor_err_msg = ""

        # ── Method 1: Cursor API ──────────────────────────────
        if progress_cb:
            progress_cb("Requesting cursor from Kintone…")
        try:
            r = requests.post(
                cursor_url,
                headers=self._headers(),
                json={"app": app_id, "size": size, "query": '$id > "0"'},
                timeout=20,
            )
            if r.status_code != 200:
                raise ValueError(f"Cursor POST {r.status_code}: {r.text[:200]}")

            cursor_id = r.json()["id"]
            page      = 0

            while True:
                page += 1
                if progress_cb:
                    progress_cb(f"[Cursor] Page {page}  •  {len(all_records):,} records loaded…")

                rc = requests.get(
                    cursor_url,
                    headers=self._get_headers(),
                    params={"id": cursor_id},
                    timeout=30,
                )
                if not rc.ok:
                    raise ValueError(f"Cursor GET {rc.status_code}: {rc.text[:200]}")

                data  = rc.json()
                batch = data.get("records", [])
                all_records.extend(batch)

                if not batch or not data.get("next", False):
                    break

            # Clean up cursor (best-effort)
            try:
                requests.delete(
                    cursor_url, headers=self._headers(),
                    json={"id": cursor_id}, timeout=10,
                )
            except Exception:
                pass

        except Exception as e:
            cursor_err_msg = str(e)
            all_records    = []
            if progress_cb:
                progress_cb("Cursor unavailable → switching to offset mode…")

            # ── Method 2: Offset pagination ───────────────────
            offset = 0
            while True:
                if progress_cb:
                    progress_cb(
                        f"[Offset] Records {offset + 1}–{offset + size}  "
                        f"•  {len(all_records):,} loaded…"
                    )
                r = requests.get(
                    records_url,
                    headers=self._get_headers(),
                    params={"app": app_id, "limit": size,
                            "offset": offset, "query": '$id > "0"'},
                    timeout=30,
                )
                if not r.ok:
                    try:
                        body = r.json().get("message", r.text[:300])
                    except Exception:
                        body = r.text[:300]
                    raise RuntimeError(
                        f"HTTP {r.status_code} — {r.reason}\n"
                        f"Kintone error: {body}\n"
                        f"Cursor also failed: {cursor_err_msg}\n"
                        "Check API token, subdomain, and App ID."
                    )
                batch = r.json().get("records", [])
                if not batch:
                    break
                all_records.extend(batch)
                offset += size
                if len(batch) < size:
                    break

        field_codes = RecordProcessor.build_field_codes(all_records)
        return all_records, field_codes

    def fetch_record_count(self) -> Optional[int]:
        """Return the live total record count, or None on error."""
        url = f"{self._cfg.kintone_base_url}/k/v1/records.json"
        try:
            r = requests.get(
                url, headers=self._get_headers(),
                params={"app": int(self._cfg.kintone_app_id),
                        "totalCount": "true", "limit": 1},
                timeout=15,
            )
            return int(r.json().get("totalCount", 0)) if r.ok else None
        except Exception:
            return None

    def fetch_field_labels(self) -> dict:
        """Return {field_code: {label, type}} from the Kintone form."""
        url = f"{self._cfg.kintone_base_url}/k/v1/app/form/fields.json"
        try:
            r = requests.get(
                url, headers=self._get_headers(),
                params={"app": int(self._cfg.kintone_app_id)}, timeout=15,
            )
            if not r.ok:
                return {}
            return {
                code: {"label": fld.get("label", code), "type": fld.get("type", "")}
                for code, fld in r.json().get("properties", {}).items()
            }
        except Exception:
            return {}

    def fetch_field_layout(self) -> list:
        """Return field codes in Kintone form layout order."""
        url = f"{self._cfg.kintone_base_url}/k/v1/app/form/layout.json"
        try:
            r = requests.get(
                url, headers=self._get_headers(),
                params={"app": int(self._cfg.kintone_app_id)}, timeout=15,
            )
            if not r.ok:
                return []
            ordered = []
            for item in r.json().get("layout", []):
                self._extract_layout_codes(item, ordered)
            return ordered
        except Exception:
            return []

    def count_data_fields(self, field_labels: dict) -> int:
        """Count only fields that store raw data (exclude CALC, LABEL, etc.)."""
        return sum(
            1 for info in field_labels.values()
            if info.get("type", "") not in self.NON_DATA_TYPES
        )

    # ── Private ───────────────────────────────────────────────
    def _extract_layout_codes(self, item: dict, out: list) -> None:
        """Recursively collect field codes in layout order."""
        t = item.get("type", "")
        if t == "ROW":
            for f in item.get("fields", []):
                self._extract_layout_codes(f, out)
        elif t == "GROUP":
            for row in item.get("layout", []):
                self._extract_layout_codes(row, out)
        elif t == "SUBTABLE":
            if code := item.get("code"):
                out.append(code)
            for col in item.get("fields", []):
                if c := col.get("code"):
                    out.append(c)
        else:
            if code := item.get("code"):
                out.append(code)
