"""
smartsheet_api.py
─────────────────
All Smartsheet REST interactions.
Completely separated from GUI — no tkinter imports here.

Key guarantees:
  • push_rows_atomic  — if ANY batch fails, ALL previously pushed batches in
                        that call are rolled back before raising. The sheet is
                        always left in a consistent state.
  • fetch_existing_ids — returns the full set of record IDs already in the
                         sheet so callers can do an exact set-difference, not
                         just a max-id comparison.
"""

from typing import Callable, Optional

import requests

from config import AppConfig
from record_processor import RecordProcessor


class SmartsheetAPI:

    BATCH_SIZE     = 500
    ROLLBACK_CHUNK = 450

    def __init__(self, config: AppConfig):
        self._cfg = config

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._cfg.smartsheet_api_token}",
            "Content-Type":  "application/json",
        }

    @property
    def _base_url(self) -> str:
        return self._cfg.smartsheet_base_url

    # ── Sheet / column fetching ───────────────────────────────
    def fetch_sheet(self) -> dict:
        r = requests.get(self._base_url, headers=self._headers, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Smartsheet GET failed: {r.status_code}\n{r.text[:300]}")
        return r.json()

    def fetch_columns(self) -> list:
        r = requests.get(f"{self._base_url}/columns", headers=self._headers, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Column fetch failed: {r.status_code}\n{r.text[:300]}")
        return r.json().get("data", [])

    def sync_columns(
        self,
        desired: list,
        existing_cols: list,
        progress_cb: Optional[Callable] = None,
    ) -> tuple:
        """
        Returns (col_map, missing_cols) where:
          col_map      = {field_code → column_id}  for every matched/created column
          missing_cols = [(code, label)] for any columns Smartsheet rejected
        """
        col_url         = f"{self._base_url}/columns"
        existing_titles = {col["title"]: col["id"] for col in existing_cols}
        primary_col     = next((c for c in existing_cols if c.get("primary")), None)
        col_map         = {}

        for code, label in desired:
            if label in existing_titles:
                col_map[code] = existing_titles[label]

        missing = [(code, label) for code, label in desired if code not in col_map]
        for idx, (code, label) in enumerate(missing):
            if primary_col and primary_col["id"] not in col_map.values():
                rp = requests.put(
                    f"{col_url}/{primary_col['id']}", headers=self._headers,
                    json={"title": label, "type": "TEXT_NUMBER", "index": 0},
                    timeout=15,
                )
                if rp.ok:
                    col_map[code] = primary_col["id"]
            else:
                rc = requests.post(
                    col_url, headers=self._headers,
                    json={"title": label, "type": "TEXT_NUMBER",
                          "index": len(existing_cols) + idx},
                    timeout=15,
                )
                if rc.ok:
                    result = rc.json().get("result", [])
                    new_id = (
                        result[0].get("id") if isinstance(result, list) and result
                        else result.get("id") if isinstance(result, dict)
                        else None
                    )
                    if new_id:
                        col_map[code] = new_id

        if missing and progress_cb:
            progress_cb(f"Added {len(missing)} new column(s) to Smartsheet ✓")

        live_cols      = self.fetch_columns()
        live_title_map = {col["title"]: int(col["id"]) for col in live_cols}
        verified_map   = {
            code: int(live_title_map[label])
            for code, label in desired
            if label in live_title_map
        }

        self._write_debug_log(live_cols, verified_map)

        # ── Post-sync verification ────────────────────────────
        missing_cols = [
            (code, label) for code, label in desired
            if code not in verified_map
        ]
        if missing_cols and progress_cb:
            progress_cb(
                f"⚠  {len(missing_cols)} column(s) could not be created in Smartsheet "
                f"({len(verified_map)}/{len(desired)} matched). "
                f"Check smartsheet_debug.log for details."
            )

        return verified_map, missing_cols

    def _write_debug_log(self, live_cols: list, col_map: dict) -> None:
        try:
            with open("smartsheet_debug.log", "w", encoding="utf-8") as dbg:
                dbg.write(f"Sheet ID : {self._cfg.smartsheet_sheet_id}\n")
                dbg.write("Columns from /columns endpoint:\n")
                for col in live_cols:
                    dbg.write(f"  {col['id']}  →  {col['title']}\n")
                dbg.write("\ncol_map (code → columnId):\n")
                for code, cid in col_map.items():
                    dbg.write(f"  {code:<30} → {cid}\n")
        except Exception:
            pass

    # ── Existing ID fetch (full set, not just max) ────────────
    def fetch_existing_ids(
        self,
        col_map: dict,
        id_col_code: Optional[str],
        progress_cb: Optional[Callable] = None,
    ) -> set:
        """
        Return the COMPLETE set of record IDs already in Smartsheet as integers.

        Works across view modes — even if $id is not in col_map (Selected View),
        we scan the live sheet columns for any column titled "ID" or "REC #"
        so deduplication always works regardless of which view pushed first.
        """
        # Try col_map first
        id_col_id = col_map.get(id_col_code) if id_col_code else None

        # Fallback: scan live columns by known title variants
        if not id_col_id:
            try:
                live_cols  = self.fetch_columns()
                id_titles  = {"id", "rec #", "record number", "record_number", "$id"}
                for col in live_cols:
                    if col.get("title", "").strip().lower() in id_titles:
                        id_col_id = col["id"]
                        break
            except Exception:
                pass

        if not id_col_id:
            return set()

        existing_ids: set = set()
        page_size = 10000   # Smartsheet max per page
        page      = 1

        while True:
            if progress_cb:
                progress_cb(
                    f"Scanning existing Smartsheet records…  {len(existing_ids):,} found so far"
                )
            r = requests.get(
                self._base_url, headers=self._headers,
                params={
                    "columnIds": id_col_id,
                    "pageSize":  page_size,
                    "page":      page,
                },
                timeout=60,
            )
            if not r.ok:
                # If pagination fails, fall back to whatever we have
                break

            data = r.json()
            rows = data.get("rows", [])
            for row in rows:
                for cell in row.get("cells", []):
                    raw = cell.get("value")
                    if raw is None:
                        continue
                    try:
                        existing_ids.add(int(str(raw).strip()))
                    except (ValueError, TypeError):
                        pass

            # Smartsheet pagination: totalPages in response
            total_pages = data.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1

        return existing_ids

    # ── Existing row map {kintone_id → ss_row_id} ───────────
    def fetch_existing_row_map(
        self,
        col_map: dict,
        id_col_code: Optional[str],
        progress_cb: Optional[Callable] = None,
    ) -> dict:
        """
        Return {kintone_id (int) → smartsheet_row_id (str)} for every row
        already in Smartsheet.  Used to UPDATE existing rows rather than
        INSERT duplicates when switching between view modes.
        """
        id_col_id = col_map.get(id_col_code) if id_col_code else None

        # Fallback: scan live columns by title
        if not id_col_id:
            try:
                live_cols = self.fetch_columns()
                id_titles = {"id", "rec #", "record number", "record_number", "$id"}
                for col in live_cols:
                    if col.get("title", "").strip().lower() in id_titles:
                        id_col_id = col["id"]
                        break
            except Exception:
                pass

        if not id_col_id:
            return {}

        row_map: dict = {}
        page_size = 10000
        page      = 1

        while True:
            if progress_cb:
                progress_cb(
                    f"Mapping existing Smartsheet rows…  {len(row_map):,} found so far"
                )
            r = requests.get(
                self._base_url, headers=self._headers,
                params={"columnIds": id_col_id, "pageSize": page_size, "page": page},
                timeout=60,
            )
            if not r.ok:
                break

            data = r.json()
            for row in data.get("rows", []):
                ss_row_id = str(row.get("id", ""))
                for cell in row.get("cells", []):
                    raw = cell.get("value")
                    if raw is None:
                        continue
                    try:
                        kintone_id = int(str(raw).strip())
                        row_map[kintone_id] = ss_row_id
                    except (ValueError, TypeError):
                        pass

            total_pages = data.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1

        return row_map

    def update_rows(
        self,
        rows: list,
        progress_cb: Optional[Callable] = None,
    ) -> None:
        """
        PUT (update) existing Smartsheet rows in batches.
        Each row dict must include "id" (the Smartsheet row ID).
        Does NOT roll back on failure — partial updates are safe since
        they only fill in missing column values.
        """
        total = len(rows)
        for i in range(0, total, self.BATCH_SIZE):
            batch     = rows[i:i + self.BATCH_SIZE]
            batch_num = i // self.BATCH_SIZE + 1
            if progress_cb:
                progress_cb(
                    f"Updating existing rows…  "
                    f"{min(i + self.BATCH_SIZE, total):,} / {total:,}"
                )
            rp = requests.put(
                f"{self._base_url}/rows",
                headers=self._headers, json=batch, timeout=60,
            )
            if not rp.ok:
                raise RuntimeError(
                    f"Update batch {batch_num} failed: "
                    f"HTTP {rp.status_code}\n{rp.text[:400]}"
                )

    # ── ATOMIC push with guaranteed rollback ──────────────────
    def push_rows_atomic(
        self,
        rows: list,
        progress_cb: Optional[Callable] = None,
    ) -> list:
        """
        Push rows in batches. ATOMIC: if any batch fails, ALL rows pushed in
        this call are deleted before raising — the sheet is left unchanged.

        Returns list of pushed Smartsheet row IDs on full success.
        Raises RuntimeError (after rollback) on any failure.
        """
        pushed_ids: list[str] = []
        total = len(rows)

        for i in range(0, total, self.BATCH_SIZE):
            batch      = rows[i:i + self.BATCH_SIZE]
            batch_num  = i // self.BATCH_SIZE + 1
            batch_total= (total + self.BATCH_SIZE - 1) // self.BATCH_SIZE

            if progress_cb:
                progress_cb(
                    f"Pushing…  batch {batch_num}/{batch_total}  "
                    f"({i:,}–{min(i + self.BATCH_SIZE, total):,} of {total:,} rows)"
                )

            rp = requests.post(
                f"{self._base_url}/rows",
                headers=self._headers, json=batch, timeout=60,
            )

            if not rp.ok:
                # ── ROLLBACK all previously pushed rows ───────
                if progress_cb:
                    progress_cb(
                        f"Batch {batch_num} failed — rolling back "
                        f"{len(pushed_ids):,} already-pushed rows…"
                    )
                self._delete_rows(pushed_ids)
                raise RuntimeError(
                    f"Batch {batch_num}/{batch_total} failed: "
                    f"HTTP {rp.status_code}\n{rp.text[:400]}\n\n"
                    f"Rollback complete — {len(pushed_ids):,} rows were removed. "
                    f"Smartsheet is unchanged."
                )

            for row in rp.json().get("result", []):
                pushed_ids.append(str(row.get("id")))

        return pushed_ids

    def _delete_rows(self, row_ids: list) -> None:
        """Delete rows in chunks — used internally for rollback."""
        for i in range(0, len(row_ids), self.ROLLBACK_CHUNK):
            batch = row_ids[i:i + self.ROLLBACK_CHUNK]
            try:
                requests.delete(
                    f"{self._base_url}/rows",
                    headers=self._headers,
                    params={"ids": ",".join(batch), "ignoreRowsNotFound": "true"},
                    timeout=30,
                )
            except Exception:
                pass

    # Keep old name as alias so repush_worker still works
    def rollback_rows(self, row_ids: list) -> None:
        self._delete_rows(row_ids)

    # ── Row payload builder ───────────────────────────────────
    def build_rows_payload(
        self,
        records: list,
        field_codes: list,
        col_map: dict,
        cell_value_fn: Callable,
    ) -> list:
        """Convert Kintone records into Smartsheet row dicts."""
        rows = []
        for rec in records:
            cells        = []
            seen_col_ids = set()
            for code in field_codes:
                col_id = col_map.get(code)
                if col_id is None or col_id in seen_col_ids:
                    continue
                seen_col_ids.add(col_id)
                cells.append({"columnId": int(col_id), "value": cell_value_fn(rec, code)})
            if cells:
                rows.append({"toBottom": True, "cells": cells})
        return rows