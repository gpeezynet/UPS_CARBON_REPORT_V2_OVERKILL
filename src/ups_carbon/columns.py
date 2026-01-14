"""Column auto-detection for UPS CSV files with varying headers."""

import re
from typing import Optional
from dataclasses import dataclass


@dataclass
class ColumnMapping:
    """Detected or overridden column mappings."""
    ship_date: Optional[str] = None
    weight: Optional[str] = None
    dest_zip: Optional[str] = None
    origin_zip: Optional[str] = None
    service: Optional[str] = None
    tracking: Optional[str] = None
    zone: Optional[str] = None
    sales_order: Optional[str] = None  # SO / Sales Order / Reference fields


# Patterns for detecting columns (case-insensitive)
COLUMN_PATTERNS = {
    "ship_date": [
        r"^ship\s*date$",
        r"^pickup\s*date$",
        r"^date\s*shipped$",
        r"^shipped\s*date$",
        r"^shipment\s*date$",
    ],
    "weight": [
        r"^billed\s*weight",
        r"^package\s*weight",
        r"^weight\s*\(?lb",
        r"^actual\s*weight",
        r"^weight$",
    ],
    "dest_zip": [
        r"^receiver\s*zip",
        r"^dest(ination)?\s*zip",
        r"^ship\s*to\s*zip",
        r"^to\s*zip",
        r"^consignee\s*zip",
        r"^delivery\s*zip",
        r"^receiver\s*postal",
        r"^dest(ination)?\s*postal",
    ],
    "origin_zip": [
        r"^sender\s*zip",
        r"^origin\s*zip",
        r"^ship\s*from\s*zip",
        r"^from\s*zip",
        r"^shipper\s*zip",
        r"^pickup\s*zip",
        r"^sender\s*postal",
        r"^origin\s*postal",
    ],
    "service": [
        r"^service\s*type$",
        r"^service\s*description$",
        r"^service$",
        r"^shipping\s*service$",
        r"^ups\s*service$",
    ],
    "tracking": [
        r"^tracking\s*(number|no\.?|#)?$",
        r"^package\s*tracking",
        r"^shipment\s*id",
        r"^1z",  # UPS tracking numbers start with 1Z
    ],
    "zone": [
        r"^zone$",
        r"^shipping\s*zone$",
        r"^ups\s*zone$",
    ],
    "sales_order": [
        r"^sales\s*order",
        r"^so$",
        r"^order\s*(number|no\.?|#|id)?$",
        r"^reference\s*(number\s*)?(1|2|3)$",
        r"^ref\s*(1|2|3)$",
        r"^po\s*(number|no\.?|#)?$",
        r"^purchase\s*order",
        r"^customer\s*ref",
    ],
}


def detect_columns(df_columns: list[str], overrides: Optional[dict] = None) -> ColumnMapping:
    """
    Auto-detect column mappings from DataFrame column names.

    Args:
        df_columns: List of column names from the CSV
        overrides: Optional dict of field->column_name overrides from CLI

    Returns:
        ColumnMapping with detected/overridden column names
    """
    overrides = overrides or {}
    mapping = ColumnMapping()

    # Normalize column names for matching
    normalized = {col: col.strip().lower() for col in df_columns}

    for field, patterns in COLUMN_PATTERNS.items():
        # Check for override first
        if field in overrides and overrides[field]:
            setattr(mapping, field, overrides[field])
            continue

        # Try to match patterns
        for col, norm_col in normalized.items():
            for pattern in patterns:
                if re.search(pattern, norm_col, re.IGNORECASE):
                    setattr(mapping, field, col)
                    break
            if getattr(mapping, field):
                break

    return mapping


def validate_required_columns(mapping: ColumnMapping) -> tuple[bool, list[str]]:
    """
    Validate that required columns are present.

    Returns:
        Tuple of (is_valid, list of missing column descriptions)
    """
    missing = []

    # Required columns
    if not mapping.weight:
        missing.append("weight (try: 'Billed Weight', 'Package Weight', 'Weight (lb)')")

    # We need either dest_zip or zone for mileage
    if not mapping.dest_zip and not mapping.zone:
        missing.append("destination ZIP or zone (try: 'Receiver Zip', 'Dest Zip', 'Zone')")

    return len(missing) == 0, missing


def get_column_detection_report(mapping: ColumnMapping) -> str:
    """Generate a human-readable report of detected columns."""
    lines = ["Column Detection Results:", "-" * 40]

    fields = [
        ("Ship Date", mapping.ship_date, "optional"),
        ("Weight", mapping.weight, "REQUIRED"),
        ("Destination ZIP", mapping.dest_zip, "required*"),
        ("Origin ZIP", mapping.origin_zip, "optional"),
        ("Service", mapping.service, "optional"),
        ("Tracking Number", mapping.tracking, "optional"),
        ("Zone", mapping.zone, "fallback*"),
        ("Sales Order", mapping.sales_order, "optional"),
    ]

    for name, value, status in fields:
        if value:
            lines.append(f"  {name}: '{value}'")
        else:
            lines.append(f"  {name}: NOT FOUND ({status})")

    lines.append("-" * 40)
    lines.append("* Either Destination ZIP or Zone is required for mileage estimation")

    return "\n".join(lines)
