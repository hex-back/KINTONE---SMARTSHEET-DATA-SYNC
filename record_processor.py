"""
record_processor.py
───────────────────
Pure-static helpers for transforming and filtering Kintone records.
No I/O, no GUI — easily unit-tested in isolation.
"""

import json
import re


class RecordProcessor:

    @staticmethod
    def cell_value(record: dict, field_code: str) -> str:
        """Extract a display string from a Kintone field dict."""
        try:
            field = record.get(field_code, {})
            if not isinstance(field, dict):
                return str(field)
            val = field.get("value", "")
            if val is None:
                return ""
            if isinstance(val, list):
                parts = []
                for item in val:
                    if isinstance(item, dict):
                        inner = (item.get("name") or item.get("value") or
                                 item.get("label") or "")
                        parts.append(str(inner) if inner else str(item))
                    else:
                        parts.append(str(item))
                return ", ".join(parts)
            if isinstance(val, dict):
                return str(val.get("name") or val.get("value") or val)
            return str(val)
        except Exception:
            return ""

    @staticmethod
    def human_label(code: str, field_labels: dict) -> str:
        """Convert a Kintone field code into a human-readable column label."""
        if code == "$id":
            return "ID"
        if code == "Record_number":
            return "REC #"
        if code in field_labels:
            return field_labels[code].get("label", code)
        return re.sub(r"([A-Z])", r" \1", code).replace("_", " ").strip().title()

    @staticmethod
    def ss_column_name(label: str) -> str:
        """Truncate a label to Smartsheet's 50-character column name limit."""
        return label[:47] + "..." if len(label) > 50 else label

    @staticmethod
    def filter_records(records: list, query: str) -> list:
        """Return records whose JSON contains *query* (case-insensitive)."""
        if not query:
            return records
        q = query.lower()
        return [r for r in records if q in json.dumps(r, ensure_ascii=False).lower()]

    @staticmethod
    def sort_records(records: list, field_code: str, reverse: bool = False) -> list:
        """Return a sorted copy of *records* by the value of *field_code*."""
        return sorted(
            records,
            key=lambda r: RecordProcessor.cell_value(r, field_code).lower(),
            reverse=reverse,
        )

    @staticmethod
    def order_by_id(records: list, descending: bool = True) -> list:
        """Sort records by numeric $id, newest first by default."""
        return sorted(
            records,
            key=lambda r: RecordProcessor.cell_value(r, "$id").zfill(10),
            reverse=descending,
        )

    @staticmethod
    def build_field_codes(records: list) -> list:
        """Derive an ordered field-code list from the first record."""
        if not records:
            return []
        sample    = records[0]
        preferred = ["Record_number", "$id"]
        others    = sorted(k for k in sample if k not in preferred and not k.startswith("$"))
        return [k for k in preferred if k in sample] + others
