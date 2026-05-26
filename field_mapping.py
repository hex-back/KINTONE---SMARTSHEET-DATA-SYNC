"""
field_mapping.py
────────────────
Kintone → Smartsheet column mapping.

Matching is done by KINTONE DISPLAY LABEL (not internal field code).
This means known fields appear in Selected View immediately — no code hunting needed.

HOW TO FILL IN THE ???? FIELDS:
  1. Run the app → click 🔎 Field Codes
  2. Browse the inspector for a field that seems to correspond to the Smartsheet column
  3. Note its Kintone Label → replace the kintone_label="" below with that label
  4. Save → re-run → it appears in Selected View

LEGEND:
  kintone_label = ""    →  Kintone field not yet identified (????)
  confirmed = False     →  Smartsheet column name also still TBD
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FieldEntry:
    kintone_label:    str   # Kintone display label — "" means unknown (????)
    smartsheet_label: str   # Exact column name to create in Smartsheet
    confirmed:        bool = True  # False = both sides still TBD


# ══════════════════════════════════════════════════════════════════
#  MAPPING  TABLE  (in Kintone form order)
#  Replace "" kintone_label values using 🔎 Field Codes inspector
# ══════════════════════════════════════════════════════════════════

FIELD_MAP: list[FieldEntry] = [
    # kintone_label                         smartsheet_label
    FieldEntry("Market Segment",            "Market Segment"),
    FieldEntry("NBO / NTO #",               "NTO No."),
    FieldEntry("",                          "Revision",                       confirmed=False),
    FieldEntry("",                          "Issued by",                      confirmed=False),
    FieldEntry("",                          "Issued date",                    confirmed=False),
    FieldEntry("",                          "Customer",                       confirmed=False),
    FieldEntry("",                          "End Customer",                   confirmed=False),
    FieldEntry("US Code",                   "US Code"),
    FieldEntry("",                          "Socket RDD",                     confirmed=False),
    FieldEntry("Project Name",              "Project Name"),
    FieldEntry("Application",               "Application"),
    FieldEntry("New Design / Design Change","New Design / Design Change"),
    FieldEntry("",                          "Concept/Footprint DWG Required", confirmed=False),
    FieldEntry("Concept Dwg Due Date",      "Concept DWG Due Date & Submission", confirmed=False),
    FieldEntry("",                          "Final DWG Due Date",             confirmed=False),
    FieldEntry("BU",                        "BU"),
    FieldEntry("",                          "Thermal Simulation Required",    confirmed=False),
    FieldEntry("Request for what kind of design", "Request for what kind of design"),
    FieldEntry("",                          "New Pin Design Required",        confirmed=False),
    FieldEntry("SI Simulation Required",    "SI Simulation Required"),
    FieldEntry("",                          "Frequency / Data Speed Required",confirmed=False),
    FieldEntry("",                          "Dimension",                      confirmed=False),
    FieldEntry("",                          "Package Material",               confirmed=False),
    FieldEntry("Lead/Pad/Ball Map",         "Lead/Pad/Ball Material"),
    FieldEntry("",                          "Lead/Pad/Ball Count",            confirmed=False),
    FieldEntry("Signal",                    "Signal"),
    FieldEntry("",                          "Mechanical Power",               confirmed=False),
    FieldEntry("",                          "Ground",                         confirmed=False),
    FieldEntry("Pitch ★",                   "Pitch"),
    FieldEntry("",                          "Die Size",                       confirmed=False),
    FieldEntry("",                          "Lead/Pad/Ball Map",              confirmed=False),
    # ↑ Two Kintone fields share the label "Lead/Pad/Ball Map".
    #   The first one (→ Lead/Pad/Ball Material above) will match by label.
    #   This second one needs its field code — use 🔎 Field Codes to find it,
    #   then replace "" with its label or handle separately.
    FieldEntry("Bare Die / Cover",          "Bare Die / Cover"),
    FieldEntry("With / Without Ring",       "With / Without Ring"),
    FieldEntry("Order Quantiry",            "Order Q'ty"),   # typo in Kintone preserved
    FieldEntry("",                          "Sales Amount",                   confirmed=False),
    FieldEntry("AMD, SLT, …",               "AMD, SLT,…"),
    FieldEntry("Tooling Required Parts",    "Tooling Required Parts"),
    FieldEntry("Total Tooling Cost (USD)",  "Tooling Cost ($)"),
    FieldEntry("Match with competitor's footprint?", "Match with competitor's footprint?"),
    FieldEntry("Project Level",             "Project Level"),
    FieldEntry("Test Type",                 "Test Type"),
    FieldEntry("Test Method",               "Test Method"),
    FieldEntry("",                          "Handler",                        confirmed=False),
    FieldEntry("",                          "Package Loading Method",         confirmed=False),
    FieldEntry("",                          "Test Temperature",               confirmed=False),
    FieldEntry("PCB Thickness",             "PCB Thickness"),
    FieldEntry("",                          "ESD Required on Socket",         confirmed=False),
    FieldEntry("Test Head Requirements?",   "Test Head Requirements"),
    FieldEntry("New Open Top Design Request","New Open Top Design Request"),
    FieldEntry("New Manual Lid Design Request","New Manual Lid Design Request"),
    FieldEntry("New Pin Design Request",    "New Pin Design Request"),
    FieldEntry("",                          "Remarks",                        confirmed=False),
]


# ══════════════════════════════════════════════════════════════════
#  DERIVED LOOKUPS  (used by KintoneViewer — do not edit below)
# ══════════════════════════════════════════════════════════════════

# Only entries whose Kintone label is known
ACTIVE_MAP: list[FieldEntry] = [e for e in FIELD_MAP if e.kintone_label != ""]

# kintone_label → smartsheet_label  (for column renaming on push)
LABEL_TO_SS: dict[str, str] = {
    e.kintone_label: e.smartsheet_label for e in ACTIVE_MAP
}

# Stats
TOTAL_FIELDS    = len(FIELD_MAP)
CONFIRMED_CODES = len(ACTIVE_MAP)
PENDING_FIELDS  = TOTAL_FIELDS - CONFIRMED_CODES