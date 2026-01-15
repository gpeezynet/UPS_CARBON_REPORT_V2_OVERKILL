"""Fill Miles column in Excel workbooks using ZIP-to-ZIP distance."""

import argparse
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import openpyxl
import pgeocode


ORIGIN_HEADERS = {
    "sender zip code",
    "origin zip",
    "origin postal code",
    "ship from zip",
    "from zip",
}
DEST_HEADERS = {
    "receiver zip code",
    "destination zip",
    "destination postal code",
    "ship to zip",
    "to zip",
}


@dataclass
class SheetSummary:
    name: str
    filled_count: int
    missing_zip_count: int
    total_rows: int


_GEOCODER: Optional[pgeocode.Nominatim] = None


def get_geocoder() -> pgeocode.Nominatim:
    global _GEOCODER
    if _GEOCODER is None:
        _GEOCODER = pgeocode.Nominatim("us")
    return _GEOCODER


@lru_cache(maxsize=10000)
def get_zip_coords(zip_code: str) -> Optional[tuple[float, float]]:
    zip_clean = normalize_zip(zip_code)
    if zip_clean is None:
        return None

    try:
        result = get_geocoder().query_postal_code(zip_clean)
    except Exception:
        return None

    if result is None:
        return None

    lat = result.latitude
    lon = result.longitude
    if lat is None or lon is None:
        return None
    try:
        if math.isnan(lat) or math.isnan(lon):
            return None
    except TypeError:
        pass

    return float(lat), float(lon)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_miles = 3958.8
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r_miles * c


def normalize_header(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def normalize_zip(value: object) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if not value.is_integer():
            return None
        value = int(value)
    if isinstance(value, bool):
        return None

    zip_str = str(value).strip()
    if not zip_str:
        return None
    zip_clean = zip_str.replace("-", "").replace(" ", "")[:5]
    if len(zip_clean) != 5 or not zip_clean.isdigit():
        return None
    return zip_clean


def is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, float):
        return math.isnan(value)
    return False


def parse_distance(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
            if match:
                return float(match.group(1))
    return None


def round_miles(value: float) -> int:
    return int(math.floor(value + 0.5))


def find_columns(sheet: openpyxl.worksheet.worksheet.Worksheet) -> tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    origin_col = None
    dest_col = None
    miles_col = None
    distance_col = None

    for col_idx in range(1, sheet.max_column + 1):
        header_norm = normalize_header(sheet.cell(row=1, column=col_idx).value)
        if not header_norm:
            continue
        if origin_col is None and header_norm in ORIGIN_HEADERS:
            origin_col = col_idx
        if dest_col is None and header_norm in DEST_HEADERS:
            dest_col = col_idx
        if miles_col is None and header_norm == "miles":
            miles_col = col_idx
        if distance_col is None and header_norm == "distance":
            distance_col = col_idx

    return origin_col, dest_col, miles_col, distance_col


def fill_miles_in_sheet(
    sheet: openpyxl.worksheet.worksheet.Worksheet,
    fallback_origin_zip: Optional[str],
) -> SheetSummary:
    origin_col, dest_col, miles_col, distance_col = find_columns(sheet)
    total_rows = max(sheet.max_row - 1, 0)
    filled_count = 0
    missing_zip_count = 0

    if miles_col is None:
        miles_col = sheet.max_column + 1
        sheet.cell(row=1, column=miles_col).value = "Miles"

    if dest_col is None:
        return SheetSummary(sheet.title, filled_count, missing_zip_count, total_rows)

    for row_idx in range(2, sheet.max_row + 1):
        miles_cell = sheet.cell(row=row_idx, column=miles_col)
        if not is_blank(miles_cell.value):
            continue

        dest_value = sheet.cell(row=row_idx, column=dest_col).value
        dest_zip = normalize_zip(dest_value)
        if dest_zip is None:
            missing_zip_count += 1
            continue

        if distance_col is not None:
            distance_value = parse_distance(sheet.cell(row=row_idx, column=distance_col).value)
            if distance_value is not None:
                miles_cell.value = round_miles(distance_value)
                filled_count += 1
                continue

        origin_zip = fallback_origin_zip
        if origin_col is not None:
            origin_value = sheet.cell(row=row_idx, column=origin_col).value
            origin_candidate = normalize_zip(origin_value)
            if origin_candidate:
                origin_zip = origin_candidate

        if origin_zip is None:
            continue

        origin_coords = get_zip_coords(origin_zip)
        dest_coords = get_zip_coords(dest_zip)
        if origin_coords is None or dest_coords is None:
            if dest_coords is None:
                missing_zip_count += 1
            continue

        miles = haversine_miles(
            origin_coords[0], origin_coords[1],
            dest_coords[0], dest_coords[1],
        )
        miles_cell.value = round_miles(miles)
        filled_count += 1

    return SheetSummary(sheet.title, filled_count, missing_zip_count, total_rows)


def build_output_path(input_path: Path) -> Path:
    suffix = input_path.suffix or ".xlsx"
    stem = input_path.stem if input_path.suffix else input_path.name
    return input_path.with_name(f"{stem}_MILES_FILLED{suffix}")


def fill_miles_in_workbook(
    input_path: Path,
    output_path: Path,
    origin_zip: Optional[str],
) -> list[SheetSummary]:
    keep_vba = input_path.suffix.lower() == ".xlsm"
    workbook = openpyxl.load_workbook(input_path, keep_vba=keep_vba)
    origin_zip_clean = normalize_zip(origin_zip) if origin_zip else None
    summaries = []

    for sheet in workbook.worksheets:
        summaries.append(fill_miles_in_sheet(sheet, origin_zip_clean))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return summaries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fill Miles column in an existing Excel workbook."
    )
    parser.add_argument(
        "--in",
        dest="in_path",
        required=True,
        help="Path to input Excel workbook",
    )
    parser.add_argument(
        "--out",
        dest="out_path",
        help="Optional output path (.xlsx). Defaults to <input>_MILES_FILLED.xlsx",
    )
    parser.add_argument(
        "--origin-zip",
        dest="origin_zip",
        default="35763",
        help="Fallback origin ZIP when a sheet has no origin ZIP column",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.in_path)
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 1

    output_path = Path(args.out_path) if args.out_path else build_output_path(input_path)
    fallback_origin = normalize_zip(args.origin_zip)
    if args.origin_zip and fallback_origin is None:
        print(f"Warning: invalid --origin-zip '{args.origin_zip}', only sheet origin zips will be used.")

    summaries = fill_miles_in_workbook(input_path, output_path, fallback_origin)
    for summary in summaries:
        print(
            f"{summary.name}: filled={summary.filled_count}, "
            f"missing_zip={summary.missing_zip_count}, total_rows={summary.total_rows}"
        )
    print(f"Saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
