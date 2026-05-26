# Kintone → Smartsheet Sync Tool

A desktop GUI application that fetches records from a Kintone app, displays them in a sortable/searchable table viewer, and syncs them to a Smartsheet — with smart deduplication, atomic rollback, and a field-mapping system that lets you curate exactly which columns get pushed.

---

## Table of Contents

1. [Overview](#overview)
2. [Requirements](#requirements)
3. [REST API Reference](#rest-api-reference)
4. [Architecture](#architecture)
5. [Module Reference](#module-reference)
6. [Installation](#installation)
7. [Configuration](#configuration)
8. [Field Mapping](#field-mapping)
9. [Using the Application](#using-the-application)
10. [Push Behaviour — INSERT vs UPDATE](#push-behaviour--insert-vs-update)
11. [Smartsheet Column Sync](#smartsheet-column-sync)
12. [Responsive UI & Font Scaling](#responsive-ui--font-scaling)
13. [Error Handling & Rollback](#error-handling--rollback)
14. [Troubleshooting](#troubleshooting)
15. [File Reference](#file-reference)

---

## Overview

The tool solves a specific data-pipeline problem: Kintone stores your records with internal field codes that don't match the column names your Smartsheet team expects. This app bridges that gap by:

- Fetching all records from Kintone (cursor API with offset fallback for reliability)
- Displaying them in a rich viewer with sort, search, and record detail
- Letting you preview a curated mapping of Kintone labels → Smartsheet column names before committing
- Pushing only new rows (INSERT) or filling missing columns on existing rows (UPDATE), never creating duplicates
- Rolling back every row from a failed push batch so Smartsheet is always left in a consistent state

---

## Requirements

### System

| Requirement | Minimum | Notes |
|---|---|---|
| Python | 3.10+ | Needed for `match` syntax and modern type hints (`list[str]`, `dict[str, str]`) |
| Operating System | Windows 10, macOS 12, Ubuntu 20.04 | `tkinter` rendering is native per OS; fonts like Segoe UI are Windows-only (fallback applies on Mac/Linux) |
| Network | Outbound HTTPS (port 443) | Both Kintone and Smartsheet APIs are cloud-hosted; no VPN or on-premise setup needed |
| Screen resolution | 900 × 600 px minimum | The window enforces `minsize(900, 600)` |

### Python packages

| Package | Version | Purpose |
|---|---|---|
| `requests` | ≥ 2.28 | All HTTP calls to Kintone and Smartsheet REST APIs |
| `customtkinter` | ≥ 5.0 | Modern-styled root window (`ctk.CTk`); appearance mode and colour theme |
| `tkinter` | stdlib | Core GUI widgets (Treeview, Entry, Label, Button, Toplevel) |
| `tkinter.ttk` | stdlib | Styled widgets: Treeview, Scrollbar |

Install third-party packages:

```bash
pip install requests customtkinter
```

On Linux, if `tkinter` is missing:

```bash
sudo apt install python3-tk
```

### API credentials

| Credential | Where to get it | Permission needed |
|---|---|---|
| Kintone API token | Kintone app → Settings → API Token | Record View (required); App Management (for field labels and layout) |
| Smartsheet API token | Smartsheet → Account → Personal Settings → API Access | Read Sheet, Write Sheet |
| Kintone App ID | Visible in the Kintone app URL: `.../k/4/` → `4` | — |
| Smartsheet Sheet ID | Visible in the Smartsheet URL: `.../sheets/669481520025476` → `669481520025476` | — |

---

## REST API Reference

Both integrations are plain REST over HTTPS using JSON request and response bodies. No SDKs are used — only the `requests` library.

### Kintone REST API

**Base URL:** `https://{subdomain}.kintone.com`

**Authentication:** Every request includes the header:
```
X-Cybozu-API-Token: <your_api_token>
```

| Method | Endpoint | Used in | Purpose |
|---|---|---|---|
| `POST` | `/k/v1/records/cursor.json` | `fetch_all_records` | Create a server-side cursor for paginated bulk fetch. Body: `{"app": id, "size": 500, "query": "$id > \"0\""}`. Returns `{"id": "<cursor_id>"}`. |
| `GET` | `/k/v1/records/cursor.json?id=<cursor_id>` | `fetch_all_records` | Fetch the next page of records using an existing cursor. Returns `{"records": [...], "next": true/false}`. |
| `DELETE` | `/k/v1/records/cursor.json` | `fetch_all_records` | Delete the cursor after use (best-effort cleanup). Body: `{"id": "<cursor_id>"}`. |
| `GET` | `/k/v1/records.json` | `fetch_all_records` | Fallback offset pagination when the cursor API fails. Params: `app`, `limit`, `offset`, `query`. |
| `GET` | `/k/v1/records.json?totalCount=true&limit=1` | `fetch_record_count` | Lightweight call to get the total record count shown in the header badge. |
| `GET` | `/k/v1/app/form/fields.json?app=<id>` | `fetch_field_labels` | Returns all field definitions: `{"properties": {"field_code": {"label": "...", "type": "..."}}}`. Used to show human-readable column headers. |
| `GET` | `/k/v1/app/form/layout.json?app=<id>` | `fetch_field_layout` | Returns the form layout tree (ROW / GROUP / SUBTABLE nesting). Recursively flattened to get field codes in the order they appear on the Kintone form. |

**Cursor vs offset fallback:**
The cursor API is the primary method because it handles datasets larger than 10,000 records (the hard offset cap) and is stateless between pages. If the API token lacks cursor permissions, the tool silently falls back to offset pagination with a progress message.

**Kintone field value shapes** (handled by `RecordProcessor.cell_value`):

| Shape | Example | Extracted as |
|---|---|---|
| Scalar string | `{"value": "Tokyo"}` | `"Tokyo"` |
| `null` | `{"value": null}` | `""` |
| List of dicts | `{"value": [{"name": "Alice"}, {"name": "Bob"}]}` | `"Alice, Bob"` |
| Dict with name | `{"value": {"name": "Option A"}}` | `"Option A"` |

---

### Smartsheet REST API

**Base URL:** `https://api.smartsheet.com/2.0/sheets/{sheet_id}`

**Authentication:** Every request includes the header:
```
Authorization: Bearer <your_api_token>
```

**Column operations:**

| Method | Endpoint | Used in | Purpose |
|---|---|---|---|
| `GET` | `/2.0/sheets/{id}` | `fetch_sheet` | Fetch the full sheet object including column definitions and metadata. |
| `GET` | `/2.0/sheets/{id}/columns` | `fetch_columns` | Fetch the current column list after sync to get authoritative column IDs. |
| `PUT` | `/2.0/sheets/{id}/columns/{col_id}` | `sync_columns` | Rename the primary column (Smartsheet's first column cannot be deleted, only renamed). |
| `POST` | `/2.0/sheets/{id}/columns` | `sync_columns` | Create a new column. Body: `{"title": "...", "type": "TEXT_NUMBER", "index": N}`. |

**Row operations:**

| Method | Endpoint | Used in | Purpose |
|---|---|---|---|
| `GET` | `/2.0/sheets/{id}?columnIds=<id>&pageSize=10000&page=N` | `fetch_existing_row_map` | Paginate through the sheet fetching only the ID column to build the deduplication map. |
| `POST` | `/2.0/sheets/{id}/rows` | `push_rows_atomic` | Insert new rows in batches of 500. Body: list of `{"toBottom": true, "cells": [{"columnId": N, "value": "..."}]}`. |
| `PUT` | `/2.0/sheets/{id}/rows` | `update_rows` | Update existing rows in batches of 500. Each row must include `"id"` (the Smartsheet row ID). |
| `DELETE` | `/2.0/sheets/{id}/rows?ids=<id1,id2,...>&ignoreRowsNotFound=true` | `_delete_rows` | Bulk-delete rows by Smartsheet row ID. Used exclusively for atomic rollback on a failed push batch. |

**Row payload shape** (built by `SmartsheetAPI.build_rows_payload`):

```json
{
  "toBottom": true,
  "cells": [
    { "columnId": 123456789, "value": "Some text" },
    { "columnId": 987654321, "value": "Another value" }
  ]
}
```

Column IDs are always cast to `int` before sending — Smartsheet rejects string IDs even when the number is correct.

**Smartsheet pagination:** The sheet GET endpoint returns `totalPages` in the response body. `fetch_existing_row_map` increments `page` until `page >= totalPages`, ensuring the full sheet is scanned even when it has more than 10,000 rows.

---

## Architecture

The codebase follows a clean layered design. Nothing in the service layer imports from the GUI layer — all coupling flows downward.

```
main.py
  └── KintoneViewer          (kintone_viewer.py)   — top-level window, orchestrator
        ├── KintoneAPI        (kintone_api.py)       — all Kintone REST calls
        ├── SmartsheetAPI     (smartsheet_api.py)    — all Smartsheet REST calls
        ├── RecordProcessor   (record_processor.py) — pure data transformation, no I/O
        ├── TableWidget       (table_widget.py)      — Treeview, scrollbars, chunked insert
        ├── FontManager       (font_manager.py)      — responsive font scaling
        ├── AppConfig         (config.py)            — all constants in one place
        ├── FIELD_MAP         (field_mapping.py)     — Kintone label → Smartsheet column
        └── Tooltip           (tooltip.py)           — hover tooltips on any widget
```

Threading model: all network operations run in daemon threads; UI updates are marshalled back to the main thread via `self.after(0, fn)`.

---

## Module Reference

### `main.py`
The sole entry point. Instantiates `KintoneViewer` and starts the Tk event loop. Nothing else lives here.

### `kintone_viewer.py` — `KintoneViewer(ctk.CTk)`
The top-level application window. It owns all UI state and orchestrates the service classes — it contains no business logic itself.

**Key responsibilities:**

| Method | Purpose |
|---|---|
| `_build_ui()` | Constructs header bar, sub-bar, search bar, table frame, and status bar |
| `_start_fetch()` | Launches background thread to fetch all Kintone records |
| `_fetch_worker()` | Background: calls `KintoneAPI.fetch_all_records()`, updates UI on completion |
| `_on_render_complete()` | Called by `TableWidget` when chunked insert finishes; updates status bar and column tooltip |
| `_sort_by(col)` | Sorts the visible dataset by a column, updates heading arrows |
| `_toggle_order()` | Toggles newest-first / oldest-first on `$id` |
| `_on_search()` | Filters records by the live search box (case-insensitive JSON scan) |
| `_on_row_double_click()` | Opens a read-only record detail popup |
| `_toggle_view_mode()` | Switches between Full View (all fields) and Selected View (mapped fields only) |
| `_push_to_smartsheet()` | Opens confirmation popup, then spawns `_smartsheet_worker` |
| `_smartsheet_worker()` | Background: syncs columns, splits records into INSERT/UPDATE, executes both |
| `_repush_by_id()` | Re-pushes a single record by its Kintone numeric ID |
| `_show_field_inspector()` | Opens the Field Code Inspector popup |
| `_active_fields()` | Returns the current field-code list for the active view mode |
| `_build_push_desired()` | Builds the `(kintone_code, smartsheet_label)` list for a push |
| `_set_ui_busy()` / `_set_ui_ready()` | Locks / unlocks all interactive controls during operations |

**View modes:**

- **Full View** — shows every field code present in the first Kintone record. Push is disabled in this mode (it would create unlabelled columns).
- **Selected View** — shows only fields whose Kintone display label is matched in `ACTIVE_MAP` (i.e. entries in `field_mapping.py` where `kintone_label != ""`). Push is enabled only in this mode.

### `kintone_api.py` — `KintoneAPI`
All Kintone REST interactions. Takes `AppConfig`; never imports from the GUI layer.

| Method | What it does |
|---|---|
| `fetch_all_records(progress_cb)` | Primary method. Tries the **Cursor API** first (most efficient, supports >10 000 records). On any cursor failure automatically falls back to **offset pagination**. Returns `(records, field_codes)`. |
| `fetch_record_count()` | Fires a lightweight `totalCount` query to get the live record count for the header badge. |
| `fetch_field_labels()` | Calls `/k/v1/app/form/fields.json` to get `{field_code: {label, type}}` — used for human-readable column headers. |
| `fetch_field_layout()` | Calls `/k/v1/app/form/layout.json` and recursively flattens ROW / GROUP / SUBTABLE structures to return field codes in form order. |
| `count_data_fields(field_labels)` | Counts only fields that store raw data, excluding `CALC`, `LABEL`, `HR`, `SPACER`, `CATEGORY`, `STATUS`, `STATUS_ASSIGNEE`, and `REFERENCE_TABLE`. Used for the column-count tooltip. |

**Cursor vs offset fallback:** The cursor API is preferred because it is stateless, handles large datasets correctly, and avoids the 10 000-record offset cap. When the server rejects a cursor (e.g. insufficient permissions), the tool switches automatically and reports progress in offset mode. The cursor is deleted (best-effort) after use.

### `smartsheet_api.py` — `SmartsheetAPI`
All Smartsheet REST interactions. Separated completely from the GUI — no tkinter imports.

| Method | What it does |
|---|---|
| `fetch_sheet()` | GET the full sheet object (columns, metadata). |
| `fetch_columns()` | GET `/columns` — used after syncing to verify what actually exists. |
| `sync_columns(desired, existing_cols, progress_cb)` | Matches desired `(code, label)` pairs against existing column titles. Renames the primary column for the first new column, then POSTs additional columns. Re-fetches live columns after creation to get authoritative IDs. Returns `(col_map, missing_cols)`. |
| `fetch_existing_ids(col_map, id_col_code, progress_cb)` | Paginates the sheet fetching only the ID column to build the full set of already-pushed record IDs. Falls back to scanning column titles if the ID column isn't in `col_map`. |
| `fetch_existing_row_map(col_map, id_col_code, progress_cb)` | Like `fetch_existing_ids` but returns `{kintone_id → smartsheet_row_id}` for UPDATE operations. |
| `push_rows_atomic(rows, progress_cb)` | Pushes rows in batches of 500. **Atomic**: if any batch fails, all previously pushed rows in this call are deleted before raising. Returns the list of pushed Smartsheet row IDs. |
| `update_rows(rows, progress_cb)` | PUT-updates existing rows in batches of 500. Partial updates are safe (only fills in column values). |
| `build_rows_payload(records, field_codes, col_map, cell_value_fn)` | Converts Kintone record dicts into Smartsheet row payload dicts, deduplicating column IDs within each row. |
| `_delete_rows(row_ids)` | Internal rollback helper — deletes rows in chunks of 450 with `ignoreRowsNotFound=true`. |
| `_write_debug_log(live_cols, col_map)` | Writes `smartsheet_debug.log` with the live column list and resolved `col_map` for diagnosing column sync issues. |

### `record_processor.py` — `RecordProcessor`
Pure-static helper class. No I/O, no GUI — fully unit-testable in isolation.

| Method | What it does |
|---|---|
| `cell_value(record, field_code)` | Extracts a display string from a Kintone field dict, handling `list`, `dict`, `None`, and scalar values. For list values, extracts `name` / `value` / `label` from each item and joins with `, `. |
| `human_label(code, field_labels)` | Converts a field code into a human-readable label. Special-cases `$id` → `"ID"` and `Record_number` → `"REC #"`. Falls back to CamelCase splitting for unmapped codes. |
| `ss_column_name(label)` | Truncates to Smartsheet's 50-character column name limit (appends `...` if truncated). |
| `filter_records(records, query)` | Case-insensitive JSON-dump search across every field in every record. Returns matching records. |
| `sort_records(records, field_code, reverse)` | Sorts by `cell_value` lowercased. Returns a new list; never mutates the original. |
| `order_by_id(records, descending)` | Sorts by numeric `$id` (zero-padded string sort for correctness). Newest first by default. |
| `build_field_codes(records)` | Derives the field-code list from the first record, placing `Record_number` and `$id` first. |

### `table_widget.py` — `TableWidget`
Owns the `ttk.Treeview`, both scrollbars, chunked row insertion, and the loading animation. Communicates with `KintoneViewer` only through callbacks — no direct coupling.

| Method | Purpose |
|---|---|
| `show_loading()` | Clears the table frame and shows a centred card with a braille spinner animation. |
| `stop_loading()` | Cancels the `after` animation loop. |
| `show_error(message)` | Shows a centred error card with the connection failure message and a hint to check `config.py`. |
| `render(records, fields, label_fn)` | Full build: creates the Treeview, measures column widths from the first 200 rows (capped at 260 px), sets headings with sort commands, then starts `_insert_chunk`. |
| `repopulate(records, fields)` | Fast re-fill for search and sort: clears rows, increments the generation counter (cancels any in-flight chunk), restarts `_insert_chunk`. |
| `_insert_chunk(records, fields, start, chunk, gen)` | Inserts `chunk` rows at a time (default 100), scheduling the next chunk via `after(0, …)` to keep the UI responsive. Stops if `gen` doesn't match `_chunk_gen` (stale operation). |
| `update_sort_arrows(fields, sort_col, sort_rev, label_fn)` | Redraws all column headings — only the active sort column gets a ▲ / ▼ arrow. |
| `resize_columns(fields, tree_width)` | Proportionally redistributes column widths to fill the current tree width. |
| `refresh_style(fonts)` | Reconfigures `ttk.Style` font entries after a breakpoint crossing. |
| `focused_item()` | Returns the IID of the currently focused Treeview row, or `None`. |

**Chunked insert:** Inserting thousands of rows at once blocks the Tk event loop. `_insert_chunk` inserts in batches of 100, yielding between batches with `after(0, …)`. This keeps the progress label updating and the window responsive during initial load and after search/sort operations.

**Generation counter:** `_chunk_gen` is incremented every time a new render or repopulate starts. Each chunk checks that its own `gen` still matches — if a new operation started (e.g. user typed in the search box while rows were still inserting), the stale chunks silently exit.

### `font_manager.py` — `FontManager`
Stateless responsive font scaling.

| Method | Purpose |
|---|---|
| `scale(width)` | Returns a `dict` of font tuples scaled to the window width. Four size tiers: ≥1400px → 11pt base, ≥1100px → 10pt, ≥900px → 9pt, <900px → 8pt. |
| `tier(width)` | Returns `"xl"` / `"lg"` / `"md"` / `"sm"` — used to detect breakpoint crossings so fonts are only re-applied when the tier actually changes. |

### `config.py` — `AppConfig`
Single source of truth for every constant. Edit credentials here — nothing else needs to change.

| Section | Fields |
|---|---|
| Kintone | `kintone_subdomain`, `kintone_app_id`, `kintone_api_token`, `kintone_fetch_size` |
| Smartsheet | `smartsheet_api_token`, `smartsheet_sheet_id` |
| Palette | `colors` dict — 18 named colour slots |
| Fonts | `fonts` dict — 7 static font tuples (dynamic sizes live in `FontManager`) |

The `kintone_base_url` and `smartsheet_base_url` properties are computed from the above values.

### `field_mapping.py`
Defines the `FieldEntry` dataclass and the `FIELD_MAP` list that maps Kintone display labels to Smartsheet column names.

Key exports:

| Name | Type | Description |
|---|---|---|
| `FIELD_MAP` | `list[FieldEntry]` | Complete mapping table including unresolved (`kintone_label=""`) entries |
| `ACTIVE_MAP` | `list[FieldEntry]` | Entries where `kintone_label != ""` — these are actually used |
| `LABEL_TO_SS` | `dict[str, str]` | `{kintone_label → smartsheet_label}` for quick rename lookup at push time |
| `TOTAL_FIELDS` | `int` | Total rows in `FIELD_MAP` |
| `CONFIRMED_CODES` | `int` | Count of entries with a known Kintone label |
| `PENDING_FIELDS` | `int` | `TOTAL_FIELDS - CONFIRMED_CODES` — shown in the ⚠ badge |

### `tooltip.py` — `Tooltip`
Lightweight hover tooltip. Binds `<Enter>` / `<Leave>` on any widget. Accepts a `text_fn: Callable[[], str]` so the tooltip content can be dynamic (e.g. the column breakdown tooltip is computed after data loads).

---

## Installation

**Requirements:** Python 3.10+

```bash
pip install requests customtkinter
```

`tkinter` and `ttk` are part of the Python standard library (included with most Python installers; on some Linux distros you may need `sudo apt install python3-tk`).

**Run the app:**

```bash
python main.py
```

---

## Configuration

Open `config.py` and fill in your credentials:

```python
kintone_subdomain:  str = "your-subdomain"      # e.g. "mycompany" → mycompany.kintone.com
kintone_app_id:     str = "4"                    # Kintone app ID (from the URL)
kintone_api_token:  str = "your-api-token"       # From Kintone App Settings → API Token

smartsheet_api_token: str = "your-ss-token"      # From Smartsheet Account → API Access
smartsheet_sheet_id:  str = "669481520025476"    # From the sheet URL
```

`kintone_fetch_size` controls how many records are requested per page (max 500). Leave at 500 for best performance.

---

## Field Mapping

`field_mapping.py` is the core configuration file for the push feature. It tells the app:

1. Which Kintone fields to include in **Selected View** and the Smartsheet push
2. What those columns should be called in Smartsheet (the label can differ from the Kintone label)

### Structure

```python
@dataclass(frozen=True)
class FieldEntry:
    kintone_label:    str   # Kintone display label — "" means not yet identified
    smartsheet_label: str   # Exact column name to create in Smartsheet
    confirmed:        bool = True
```

### Workflow for filling in unknown fields (`????`)

1. Run the app → click **🔎 Field Codes** in the toolbar.
2. The inspector shows every field code loaded from the live Kintone app, its human label, type, and whether it is already in the mapping.
3. Click any row to copy its Kintone field code to the clipboard.
4. In `field_mapping.py`, find the `FieldEntry` row whose `smartsheet_label` matches what you're trying to map. Replace `kintone_label=""` with the display label you found in the inspector.
5. Save the file and restart the app (or click Refresh).

The ⚠ badge in the toolbar shows how many entries remain unresolved. Hover over it for a list of every pending Smartsheet column name.

### Matching rules

- Matching is done by **Kintone display label** (not internal field code). This is intentional — labels are stable and human-readable; field codes change when a form is rebuilt.
- Matching is **case-insensitive** and ignores leading/trailing whitespace.
- If two Kintone fields share the same label (e.g. `Lead/Pad/Ball Map` appears twice in the sample), only the first match is used. The second must be identified by its field code and given a unique label.

---

## Using the Application

### Startup

On launch the app immediately fetches field labels and layout from Kintone (fast, ~1–2 API calls), then begins fetching all records in the background. A spinner animation is shown during the fetch.

### Toolbar controls

| Control | Action |
|---|---|
| **↺ Refresh** | Re-fetches all records from Kintone from scratch |
| **↕ Newest First / Oldest First** | Toggles sort order by `$id` |
| **🗂 Full View / 📋 Selected View** | Switches between viewing all fields or only mapped fields |
| **⬇ PUSH TO SMARTSHEET** | Opens the push confirmation popup (only available in Selected View) |
| **⚠ N fields TBD** | Hover for list of unresolved field mappings |
| **🔎 Field Codes** | Opens the Field Code Inspector popup |
| **Re-push ID** | Enter a Kintone record ID and click ↩ to re-push that single record |

### Search

Type anything in the search bar to filter records. The search scans the full JSON of every record — it matches any field value, not just visible columns. The match count is shown next to the search box.

### Sort

Click any column heading to sort ascending; click again to sort descending. A ▲ / ▼ arrow indicates the active sort column.

### Record detail

Double-click any row to open a read-only popup showing every field and value for that record in a scrollable text pane.

### Field Code Inspector

The inspector popup shows a table with four columns:

- **Status** — ✓ mapped (green), ? pending (amber), — not in mapping (grey)
- **Kintone Field Code** — the internal code; click a row to copy it to clipboard
- **Kintone Label** — the human-readable display label
- **Type** — the Kintone field type (e.g. `SINGLE_LINE_TEXT`, `DROP_DOWN`, `CALC`)
- **Smartsheet Column Target** — where this field lands in Smartsheet (from `LABEL_TO_SS`)

The header shows how many of the loaded fields are already mapped.

---

## Push Behaviour — INSERT vs UPDATE

The push is designed to be safe to run multiple times without creating duplicates or overwriting data:

1. **Column sync** — ensures every desired column exists in Smartsheet (creates missing ones).
2. **ID anchor** — `$id` is always included in the payload as a deduplication anchor, even if it's not displayed in Selected View.
3. **Fetch existing rows** — scans the Smartsheet ID column to build `{kintone_id → smartsheet_row_id}`.
4. **Split** — records are split into:
   - **INSERT** (new records): pushed via `push_rows_atomic` (batches of 500, with rollback on failure)
   - **UPDATE** (existing records): pushed via `update_rows` (batches of 500, fills missing column values only)
5. **Result** — status bar shows `N inserted • M updated`.

**Cross-view-mode safety:** If you pushed in Full View first and then switch to Selected View and push again, the existing rows are updated with the Selected View's column values — no duplicates are created.

---

## Smartsheet Column Sync

`sync_columns` handles the mismatch between what you want and what Smartsheet has:

- It matches by **column title** (case-sensitive, exact match).
- The **primary column** (first column, cannot be deleted in Smartsheet) is renamed to the first unmatched desired column.
- All other missing columns are appended via POST.
- After creation, it re-fetches live columns to get authoritative column IDs — this avoids race conditions where Smartsheet returns a placeholder ID.
- If any columns are rejected (e.g. name too long, duplicate title), a warning is shown in the status bar and the details are written to `smartsheet_debug.log`.

### `smartsheet_debug.log`

Written after every column sync. Contains:
- The sheet ID
- Every column currently in the sheet (`id → title`)
- The final `col_map` (`field_code → columnId`)

Useful when push succeeds but data appears in the wrong columns.

---

## Responsive UI & Font Scaling

The window has a minimum size of 900 × 600 px. As it is resized:

- **Font tier changes** (`xl` ≥ 1400 / `lg` ≥ 1100 / `md` ≥ 900 / `sm` < 900) trigger a full font refresh of all labelled widgets.
- **Column widths** are redistributed proportionally to fill the new tree width.
- **The DELETED stat row** is hidden below 1050 px to reduce crowding.
- **The Push button label** shortens from `PUSH TO SMARTSHEET` to `EXPORT` below 1100 px.

---

## Error Handling & Rollback

### Fetch errors
If both the cursor API and offset fallback fail, an error card is shown in the table area with the HTTP status, the Kintone error message, and a hint to check credentials.

### Push errors — atomic rollback
`push_rows_atomic` guarantees that a failed push leaves Smartsheet unchanged:

1. Rows are pushed in batches of 500.
2. Each batch's returned row IDs are tracked in `pushed_ids`.
3. If any batch fails, all rows in `pushed_ids` are deleted in chunks of 450 before the exception is raised.
4. The error popup shows the batch number, HTTP status, Kintone error body, and a confirmation that rollback completed.

UPDATE operations (`update_rows`) do not roll back because partial column fills are safe — they only add data, never remove it.

### Column sync warnings
If Smartsheet rejects a column creation request (e.g. the sheet is locked, a column with that title already exists under a different case), the push proceeds with whatever columns were successfully mapped, and a warning is shown. The rejected columns are listed in `smartsheet_debug.log`.

---

## Troubleshooting

**"Connection Error" on startup**
- Check `kintone_subdomain`, `kintone_app_id`, and `kintone_api_token` in `config.py`.
- Ensure the API token has **Record View** permission in Kintone App Settings → API Token.
- For the field inspector and layout order, the token also needs **App Management** permission.

**Records load but columns are wrong / missing**
- Open `smartsheet_debug.log` to see what column IDs were resolved.
- Check that `smartsheet_sheet_id` in `config.py` is the correct sheet.
- Confirm the API token has **Write** permission on that sheet in Smartsheet.

**Push button is greyed out**
- The push is only available in **Selected View**. Click `🗂 Full View` to toggle to `📋 Selected View`. If no mapped fields are found, the button will open a warning instead.

**⚠ N fields TBD badge shows a high number**
- Hover over the badge to see which Smartsheet columns don't have a Kintone label yet.
- Use **🔎 Field Codes** to find the matching Kintone labels, then fill them in to `field_mapping.py`.

**Data in wrong Smartsheet columns after a push**
- This usually means column titles in Smartsheet don't exactly match `smartsheet_label` values in `FIELD_MAP` (case-sensitive).
- Check `smartsheet_debug.log` and compare the `col_map` entries against the actual column titles.

**App is slow when loading many records**
- `kintone_fetch_size` is already at the maximum (500). Large datasets are fetched as fast as the API allows. The table's chunked insert keeps the UI responsive during rendering.

---

## File Reference

| File | Role |
|---|---|
| `main.py` | Entry point |
| `kintone_viewer.py` | Top-level window and application orchestrator |
| `kintone_api.py` | Kintone REST API client |
| `smartsheet_api.py` | Smartsheet REST API client |
| `record_processor.py` | Pure data transformation utilities |
| `table_widget.py` | Treeview widget with chunked insert and loading animation |
| `font_manager.py` | Responsive font scaling |
| `config.py` | Credentials and constants |
| `field_mapping.py` | Kintone label → Smartsheet column mapping table |
| `tooltip.py` | Hover tooltip widget |
| `smartsheet_debug.log` | Generated at push time — column sync diagnostics |
