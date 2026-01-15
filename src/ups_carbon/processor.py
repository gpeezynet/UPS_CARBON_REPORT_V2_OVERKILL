"""Main data processor for UPS shipping reports."""

import re
import pandas as pd
import numpy as np
from typing import Optional
from pathlib import Path

from .columns import ColumnMapping, detect_columns, validate_required_columns, get_column_detection_report
from .mileage import estimate_miles
from .emissions import calculate_emissions, detect_transport_mode
from .constants import DEFAULT_ROAD_FACTOR, DEFAULT_ZONE_MILES, EMISSION_FACTORS

TRACKING_PATTERN = re.compile(r"^1Z[0-9A-Z]{16}$")

MSC_REQUIRED_COLUMNS = {
    "tracking": [r"^tracking\s*number$"],
    "pickup_date": [r"^pickup\s*date$"],
    "service": [r"^service\s*level$"],
    "weight": [r"^weight$"],
    "receiver_zip": [r"^receiver\s*zip(\s*code)?$"],
    "reference": [r"^reference\s*no\.?\s*1\b"],
    "billed_charge": [r"^billed\s*charge$"],
    "incentive_credit": [r"^incentive\s*credit$"],
}

MSC_OPTIONAL_COLUMNS = {
    "sender_zip": [r"^sender\s*zip(\s*code)?$"],
}


class UPSReportProcessor:
    """Processes UPS shipping CSV files and calculates emissions."""

    def __init__(
        self,
        origin_zip: Optional[str] = None,
        road_factor: float = DEFAULT_ROAD_FACTOR,
        zone_miles_map: Optional[dict[int, int]] = None,
        column_overrides: Optional[dict] = None,
    ):
        """
        Initialize the processor.

        Args:
            origin_zip: Default origin ZIP if not in data
            road_factor: Multiplier for haversine to road distance
            zone_miles_map: Custom zone-to-miles mapping
            column_overrides: Dict of field->column_name overrides
        """
        self.origin_zip = origin_zip
        self.road_factor = road_factor
        self.zone_miles_map = zone_miles_map or DEFAULT_ZONE_MILES
        self.column_overrides = column_overrides or {}
        self.mapping: Optional[ColumnMapping] = None
        self.input_format = "standard"
        self._msc_columns: Optional[dict[str, str]] = None

    def load_csv(self, csv_path: str | Path) -> pd.DataFrame:
        """Load and validate a UPS CSV file."""
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")

        # Try different encodings
        for encoding in ["utf-8", "latin-1", "cp1252"]:
            try:
                df = pd.read_csv(path, encoding=encoding, dtype=str)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(f"Could not decode CSV file: {path}")

        return df

    def detect_and_validate_columns(self, df: pd.DataFrame) -> ColumnMapping:
        """Detect columns and validate required fields are present."""
        self._msc_columns = self._detect_monthly_shipping_costs_columns(list(df.columns))
        self.input_format = "monthly_shipping_costs" if self._msc_columns else "standard"
        self.mapping = detect_columns(list(df.columns), self.column_overrides)

        is_valid, missing = validate_required_columns(self.mapping)
        if not is_valid:
            report = get_column_detection_report(self.mapping)
            raise ValueError(
                f"Missing required columns:\n"
                f"  - {chr(10).join(missing)}\n\n"
                f"{report}\n\n"
                f"Use --col-* flags to specify column names manually."
            )

        return self.mapping

    def _match_column(self, df_columns: list[str], patterns: list[str]) -> Optional[str]:
        """Find the first column matching any pattern."""
        for col in df_columns:
            norm_col = col.strip().lower()
            for pattern in patterns:
                if re.search(pattern, norm_col):
                    return col
        return None

    def _detect_monthly_shipping_costs_columns(
        self, df_columns: list[str]
    ) -> Optional[dict[str, str]]:
        """Detect Monthly Shipping Costs columns and return a mapping if present."""
        col_map: dict[str, str] = {}
        for field, patterns in MSC_REQUIRED_COLUMNS.items():
            match = self._match_column(df_columns, patterns)
            if not match:
                return None
            col_map[field] = match

        for field, patterns in MSC_OPTIONAL_COLUMNS.items():
            match = self._match_column(df_columns, patterns)
            if match:
                col_map[field] = match

        return col_map

    def _parse_currency(self, value) -> Optional[float]:
        """Parse currency strings like $13.48 or $(0.65) into floats."""
        if pd.isna(value) or value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None

        negative = False
        if "(" in text and ")" in text:
            negative = True
            text = text.replace("(", "").replace(")", "")

        text = text.replace("$", "").replace(",", "").strip()
        if text in ("", "-"):
            return 0.0

        try:
            amount = float(text)
        except (ValueError, TypeError):
            return None

        if negative:
            return -abs(amount)
        return amount

    def _extract_zip5(self, value) -> Optional[str]:
        """Extract first 5 digits from ZIP strings."""
        if pd.isna(value) or value is None:
            return None
        match = re.search(r"(\d{5})", str(value))
        return match.group(1) if match else None

    def _first_nonblank(self, values) -> Optional[str]:
        """Return the first non-blank string from a list/series."""
        for val in values:
            if pd.notna(val):
                text = str(val).strip()
                if text:
                    return text
        return None

    def _is_valid_tracking(self, row: pd.Series) -> bool:
        """Return True if the row's tracking column (if present) looks like a UPS tracking number."""
        if not self.mapping or not self.mapping.tracking:
            return True
        tracking = row.get(self.mapping.tracking)
        if pd.isna(tracking):
            return False
        tracking_str = str(tracking).strip().upper()
        if not tracking_str:
            return False
        return bool(TRACKING_PATTERN.match(tracking_str))

    def _normalize_monthly_shipping_costs(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize UPS Monthly Shipping Costs export into standard columns.

        Returns a DataFrame with one row per tracking number plus
        any invalid-tracking rows (for exceptions).
        """
        col_map = self._msc_columns or self._detect_monthly_shipping_costs_columns(list(df.columns))
        if not col_map:
            return df

        tracking_col = col_map["tracking"]
        pickup_col = col_map["pickup_date"]
        service_col = col_map["service"]
        weight_col = col_map["weight"]
        receiver_col = col_map["receiver_zip"]
        reference_col = col_map["reference"]
        billed_col = col_map["billed_charge"]
        credit_col = col_map["incentive_credit"]
        sender_col = col_map.get("sender_zip")

        df_copy = df.copy()

        tracking_clean = df_copy[tracking_col].fillna("").astype(str).str.strip().str.upper()
        valid_mask = tracking_clean.str.match(TRACKING_PATTERN)

        billed = df_copy[billed_col].apply(self._parse_currency)
        credit = df_copy[credit_col].apply(self._parse_currency)
        net_cost = billed.fillna(0) + credit.fillna(0)

        dest_zip5 = df_copy[receiver_col].apply(self._extract_zip5)
        if sender_col:
            origin_zip5 = df_copy[sender_col].apply(self._extract_zip5)
        else:
            origin_zip5 = pd.Series([None] * len(df_copy), index=df_copy.index)

        valid_df = df_copy[valid_mask].copy()
        valid_df["_tracking_clean"] = tracking_clean[valid_mask]
        valid_df["_net_cost"] = net_cost[valid_mask]
        valid_df["_billed_charge"] = billed[valid_mask]
        valid_df["_dest_zip5"] = dest_zip5[valid_mask]
        valid_df["_origin_zip5"] = origin_zip5[valid_mask]

        invalid_df = df_copy[~valid_mask].copy()
        invalid_df["_tracking_clean"] = tracking_clean[~valid_mask]
        invalid_df["_net_cost"] = net_cost[~valid_mask]
        invalid_df["_dest_zip5"] = dest_zip5[~valid_mask]
        invalid_df["_origin_zip5"] = origin_zip5[~valid_mask]

        normalized_rows: list[dict] = []

        for tracking, group in valid_df.groupby("_tracking_clean"):
            net_abs = group["_net_cost"].abs()
            pick_idx = net_abs.idxmax()
            billed_abs = group["_billed_charge"].abs()
            if net_abs.max() == 0 and billed_abs.notna().any():
                pick_idx = billed_abs.idxmax()
            pick_row = group.loc[pick_idx]

            pickup_date = self._first_nonblank(group[pickup_col])
            pickup_dates = pd.to_datetime(group[pickup_col], errors="coerce")
            if pickup_dates.notna().any():
                min_idx = pickup_dates.idxmin()
                pickup_date = group.loc[min_idx, pickup_col]

            sales_order = self._first_nonblank(group[reference_col])
            origin_zip = self._first_nonblank(group["_origin_zip5"]) if sender_col else None
            dest_zip = self._first_nonblank(group["_dest_zip5"])

            row_data = {
                tracking_col: tracking,
                pickup_col: pickup_date,
                service_col: pick_row.get(service_col),
                weight_col: pick_row.get(weight_col),
                receiver_col: dest_zip,
                reference_col: sales_order,
                "total_cost_usd": round(group["_net_cost"].sum(), 2),
            }
            if sender_col:
                row_data[sender_col] = origin_zip

            normalized_rows.append(row_data)

        for _, row in invalid_df.iterrows():
            row_data = {
                tracking_col: row.get("_tracking_clean") if pd.notna(row.get("_tracking_clean")) else "",
                pickup_col: row.get(pickup_col),
                service_col: row.get(service_col),
                weight_col: row.get(weight_col),
                receiver_col: row.get("_dest_zip5"),
                reference_col: self._first_nonblank([row.get(reference_col)]),
                "total_cost_usd": round(row.get("_net_cost", 0.0), 2),
            }
            if sender_col:
                row_data[sender_col] = row.get("_origin_zip5")
            normalized_rows.append(row_data)

        normalized_df = pd.DataFrame(normalized_rows).reset_index(drop=True)
        return normalized_df

    def _safe_float(self, value) -> Optional[float]:
        """Safely convert value to float."""
        if pd.isna(value) or value == "" or value is None:
            return None
        try:
            return float(str(value).replace(",", "").strip())
        except (ValueError, TypeError):
            return None

    def _safe_int(self, value) -> Optional[int]:
        """Safely convert value to int."""
        if pd.isna(value) or value == "" or value is None:
            return None
        try:
            return int(float(str(value).strip()))
        except (ValueError, TypeError):
            return None

    def _get_order_id(self, row: pd.Series, idx: int) -> str:
        """
        Determine order_id for a row using priority:
        1. Sales Order (if non-blank)
        2. Tracking Number (if present)
        3. ROW-<index>
        """
        # Check Sales Order
        if self.mapping.sales_order:
            so = row.get(self.mapping.sales_order)
            if pd.notna(so) and str(so).strip():
                return str(so).strip()

        # Check Tracking Number
        if self.mapping.tracking:
            tracking = row.get(self.mapping.tracking)
            if pd.notna(tracking) and str(tracking).strip():
                return str(tracking).strip()

        # Fallback to row index
        return f"ROW-{idx}"

    def process(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, int]:
        """
        Process the DataFrame and calculate emissions for each row.

        Args:
            df: Input DataFrame from UPS CSV

        Returns:
            Tuple of (shipments_df, exceptions_df, raw_row_count)
        """
        if self.mapping is None:
            self.detect_and_validate_columns(df)

        raw_row_count = len(df)
        if self.input_format == "monthly_shipping_costs":
            processing_df = self._normalize_monthly_shipping_costs(df)
        else:
            processing_df = df.copy()

        shipments: list[dict] = []
        exceptions: list[dict] = []

        for idx, row in processing_df.iterrows():
            record = {"_original_index": idx}

            # Copy original columns
            for col in processing_df.columns:
                record[col] = row[col]

            # Determine order_id
            record["order_id"] = self._get_order_id(row, idx)

            # Get weight
            weight = None
            if self.mapping.weight:
                weight = self._safe_float(row.get(self.mapping.weight))
            record["weight_lb"] = weight

            # Get origin ZIP (from data or default)
            origin = self.origin_zip
            if self.mapping.origin_zip:
                row_origin = row.get(self.mapping.origin_zip)
                if pd.notna(row_origin) and str(row_origin).strip():
                    origin = str(row_origin).strip()
            record["origin_zip"] = origin

            # Get destination ZIP
            dest = None
            if self.mapping.dest_zip:
                dest_val = row.get(self.mapping.dest_zip)
                if pd.notna(dest_val):
                    dest = str(dest_val).strip()
            record["dest_zip"] = dest

            # Get zone
            zone = None
            if self.mapping.zone:
                zone = self._safe_int(row.get(self.mapping.zone))
            record["zone"] = zone

            # Get service
            service = None
            if self.mapping.service:
                svc = row.get(self.mapping.service)
                if pd.notna(svc):
                    service = str(svc).strip()
            record["service"] = service

            # Estimate miles
            miles, method = estimate_miles(
                origin, dest, zone,
                self.road_factor, self.zone_miles_map
            )
            record["miles_est"] = miles
            record["miles_method"] = method

            # Detect mode and calculate emissions
            mode = detect_transport_mode(service)
            record["mode_est"] = mode

            emissions = calculate_emissions(weight, miles, service)
            record["ton_miles"] = emissions["ton_miles"]
            record["kg_co2_est"] = emissions["kg_co2"]

            # Track exceptions
            exception_reasons = []
            if weight is None:
                exception_reasons.append("missing_weight")
            if miles is None:
                exception_reasons.append("missing_miles")
            valid_tracking = self._is_valid_tracking(row)
            if not valid_tracking:
                exception_reasons.append("invalid_tracking")

            record["is_exception"] = len(exception_reasons) > 0
            record["exception_reason"] = "; ".join(exception_reasons) if exception_reasons else None

            if record["is_exception"]:
                exceptions.append(record)
            if valid_tracking:
                shipments.append(record)

        shipments_df = pd.DataFrame(shipments)
        exceptions_df = pd.DataFrame(exceptions)
        return shipments_df, exceptions_df, raw_row_count

    def create_order_rollup(self, detail_df: pd.DataFrame) -> pd.DataFrame:
        """
        Create order-level rollup from package-level detail.

        Groups by order_id and calculates:
        - packages count
        - total weight
        - miles statistics
        - mode estimation (air if any package is air)
        - order-level emissions
        """
        if detail_df.empty:
            return pd.DataFrame()

        def agg_order(group):
            """Aggregate function for order grouping."""
            # Get unique dest ZIPs
            dest_zips = group["dest_zip"].dropna().unique()

            # Miles statistics
            miles_vals = group["miles_est"].dropna()
            miles_min = miles_vals.min() if len(miles_vals) > 0 else None
            miles_max = miles_vals.max() if len(miles_vals) > 0 else None
            miles_first = miles_vals.iloc[0] if len(miles_vals) > 0 else None

            # Inconsistency flag
            miles_inconsistent = False
            if miles_min is not None and miles_max is not None:
                if miles_min != miles_max:
                    miles_inconsistent = True
            if len(dest_zips) > 1:
                miles_inconsistent = True

            # Mode: air if ANY package is air
            modes = group["mode_est"].unique()
            order_mode = "air" if "air" in modes else "ground"

            # Total weight
            total_weight = group["weight_lb"].sum()
            if pd.isna(total_weight):
                total_weight = None

            # Order-level ton-miles and CO2
            order_ton_miles = None
            order_kg_co2 = None
            if total_weight and miles_first:
                order_ton_miles = (total_weight / 2000) * miles_first
                factor = EMISSION_FACTORS.get(order_mode, EMISSION_FACTORS["ground"])
                order_kg_co2 = order_ton_miles * factor

            return pd.Series({
                "packages": len(group),
                "total_weight_lb": total_weight,
                "miles_est": miles_first,
                "miles_min": miles_min,
                "miles_max": miles_max,
                "miles_inconsistent": miles_inconsistent,
                "dest_zips": ", ".join(str(z) for z in dest_zips) if len(dest_zips) > 0 else None,
                "mode_est": order_mode,
                "order_ton_miles": round(order_ton_miles, 4) if order_ton_miles else None,
                "order_kg_co2_est": round(order_kg_co2, 4) if order_kg_co2 else None,
                "has_exceptions": group["is_exception"].any(),
            })

        rollup = detail_df.groupby("order_id", as_index=False).apply(
            agg_order, include_groups=False
        )

        # Sort by order_id
        rollup = rollup.sort_values("order_id").reset_index(drop=True)

        return rollup
