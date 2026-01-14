"""Main data processor for UPS shipping reports."""

import pandas as pd
import numpy as np
from typing import Optional
from pathlib import Path

from .columns import ColumnMapping, detect_columns, validate_required_columns, get_column_detection_report
from .mileage import estimate_miles
from .emissions import calculate_emissions, detect_transport_mode
from .constants import DEFAULT_ROAD_FACTOR, DEFAULT_ZONE_MILES, EMISSION_FACTORS


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

    def process(self, df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
        """
        Process the DataFrame and calculate emissions for each row.

        Args:
            df: Input DataFrame from UPS CSV

        Returns:
            Tuple of (processed_df, exceptions_list)
        """
        if self.mapping is None:
            self.detect_and_validate_columns(df)

        results = []
        exceptions = []

        for idx, row in df.iterrows():
            record = {"_original_index": idx}

            # Copy original columns
            for col in df.columns:
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

            record["is_exception"] = len(exception_reasons) > 0
            record["exception_reason"] = "; ".join(exception_reasons) if exception_reasons else None

            results.append(record)

            if record["is_exception"]:
                exceptions.append(record)

        return pd.DataFrame(results), exceptions

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
