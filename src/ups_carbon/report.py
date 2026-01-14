"""Excel report generation with multiple summary tabs."""

import pandas as pd
from pathlib import Path
from typing import Optional
from datetime import datetime

from .constants import EMISSION_FACTORS, DEFAULT_ZONE_MILES, DEFAULT_ROAD_FACTOR


def generate_excel_report(
    detail_df: pd.DataFrame,
    order_rollup_df: pd.DataFrame,
    output_path: str | Path,
    input_filename: str = "input.csv",
):
    """
    Generate Excel report with multiple summary tabs.

    Tabs:
    - overall: Summary statistics
    - by_month: Emissions by month
    - by_mode: Emissions by transport mode
    - by_service: Emissions by UPS service type
    - by_order: Order-level rollup
    - exceptions: Rows with missing/invalid data
    """
    output_path = Path(output_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Overall summary
        overall_stats = _create_overall_summary(detail_df, input_filename)
        overall_stats.to_excel(writer, sheet_name="overall", index=False)

        # By month
        by_month = _create_by_month_summary(detail_df)
        by_month.to_excel(writer, sheet_name="by_month", index=False)

        # By mode
        by_mode = _create_by_mode_summary(detail_df)
        by_mode.to_excel(writer, sheet_name="by_mode", index=False)

        # By service
        by_service = _create_by_service_summary(detail_df)
        by_service.to_excel(writer, sheet_name="by_service", index=False)

        # By order
        order_rollup_df.to_excel(writer, sheet_name="by_order", index=False)

        # Exceptions
        exceptions_df = detail_df[detail_df["is_exception"] == True].copy()
        if len(exceptions_df) > 0:
            # Select relevant columns for exceptions
            exc_cols = ["order_id", "exception_reason", "weight_lb", "origin_zip",
                        "dest_zip", "zone", "service", "miles_est"]
            exc_cols = [c for c in exc_cols if c in exceptions_df.columns]
            exceptions_df[exc_cols].to_excel(writer, sheet_name="exceptions", index=False)
        else:
            # Empty exceptions sheet
            pd.DataFrame({"message": ["No exceptions found"]}).to_excel(
                writer, sheet_name="exceptions", index=False
            )


def _create_overall_summary(df: pd.DataFrame, input_filename: str) -> pd.DataFrame:
    """Create overall summary statistics."""
    total_packages = len(df)
    total_weight = df["weight_lb"].sum()
    total_ton_miles = df["ton_miles"].sum()
    total_kg_co2 = df["kg_co2_est"].sum()
    total_exceptions = df["is_exception"].sum()

    # Unique orders
    unique_orders = df["order_id"].nunique()

    # Air vs ground breakdown
    air_packages = len(df[df["mode_est"] == "air"])
    ground_packages = len(df[df["mode_est"] == "ground"])

    stats = [
        ("Report Generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("Input File", input_filename),
        ("", ""),
        ("Total Packages", total_packages),
        ("Unique Orders", unique_orders),
        ("Total Weight (lb)", f"{total_weight:,.1f}" if pd.notna(total_weight) else "N/A"),
        ("", ""),
        ("Air Packages", air_packages),
        ("Ground Packages", ground_packages),
        ("", ""),
        ("Total Ton-Miles", f"{total_ton_miles:,.2f}" if pd.notna(total_ton_miles) else "N/A"),
        ("Total kg CO2 (est)", f"{total_kg_co2:,.2f}" if pd.notna(total_kg_co2) else "N/A"),
        ("Total Metric Tons CO2", f"{total_kg_co2/1000:,.4f}" if pd.notna(total_kg_co2) else "N/A"),
        ("", ""),
        ("Exceptions (missing data)", int(total_exceptions)),
        ("Exception Rate", f"{100*total_exceptions/total_packages:.1f}%" if total_packages > 0 else "N/A"),
    ]

    return pd.DataFrame(stats, columns=["Metric", "Value"])


def _create_by_month_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Create summary by month."""
    # Try to find a date column
    date_col = None
    for col in df.columns:
        if "date" in col.lower():
            date_col = col
            break

    if date_col is None:
        return pd.DataFrame({"message": ["No date column found for monthly breakdown"]})

    df_copy = df.copy()

    # Parse dates
    df_copy["_date"] = pd.to_datetime(df_copy[date_col], errors="coerce")
    df_copy["_month"] = df_copy["_date"].dt.to_period("M")

    # Group by month
    monthly = df_copy.groupby("_month").agg({
        "order_id": "count",
        "weight_lb": "sum",
        "ton_miles": "sum",
        "kg_co2_est": "sum",
    }).reset_index()

    monthly.columns = ["Month", "Packages", "Total Weight (lb)", "Ton-Miles", "kg CO2"]
    monthly["Month"] = monthly["Month"].astype(str)

    return monthly


def _create_by_mode_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Create summary by transport mode."""
    mode_summary = df.groupby("mode_est").agg({
        "order_id": "count",
        "weight_lb": "sum",
        "ton_miles": "sum",
        "kg_co2_est": "sum",
    }).reset_index()

    mode_summary.columns = ["Mode", "Packages", "Total Weight (lb)", "Ton-Miles", "kg CO2"]

    # Add emission factor info
    mode_summary["Emission Factor (kg CO2/ton-mile)"] = mode_summary["Mode"].map(EMISSION_FACTORS)

    return mode_summary


def _create_by_service_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Create summary by UPS service type."""
    if "service" not in df.columns or df["service"].isna().all():
        return pd.DataFrame({"message": ["No service column found"]})

    service_summary = df.groupby("service").agg({
        "order_id": "count",
        "weight_lb": "sum",
        "mode_est": lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else "unknown",
        "ton_miles": "sum",
        "kg_co2_est": "sum",
    }).reset_index()

    service_summary.columns = ["Service", "Packages", "Total Weight (lb)", "Mode", "Ton-Miles", "kg CO2"]

    return service_summary.sort_values("Packages", ascending=False)


def generate_assumptions_md(
    output_path: str | Path,
    origin_zip: Optional[str] = None,
    road_factor: float = DEFAULT_ROAD_FACTOR,
    zone_miles_map: Optional[dict] = None,
):
    """Generate ASSUMPTIONS.md file explaining methodology."""
    zone_map = zone_miles_map or DEFAULT_ZONE_MILES

    content = f"""# UPS Carbon Report - Methodology & Assumptions

Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Overview

This report estimates CO2 emissions from UPS shipping data using a **ton-mile** methodology.
Emissions are calculated as: `kg_CO2 = (weight_lb / 2000) * miles * emission_factor`

## Mileage Estimation

### Method 1: ZIP-to-ZIP Distance (Primary)

When both origin and destination ZIP codes are available:
1. ZIP code centroids are looked up using the **pgeocode** library (US postal data)
2. Great-circle (haversine) distance is calculated between centroids
3. Distance is multiplied by a **road factor of {road_factor}** to approximate actual road miles

**Origin ZIP Used:** {origin_zip if origin_zip else "From data (per-row)"}

### Method 2: Zone-to-Miles Fallback

When ZIP-to-ZIP calculation fails, UPS shipping zones are mapped to approximate distances:

| Zone | Estimated Miles |
|------|-----------------|
"""

    for zone, miles in sorted(zone_map.items()):
        content += f"| {zone} | {miles} |\n"

    content += f"""
## Emission Factors

CO2 emissions use EPA SmartWay-aligned factors for freight:

| Mode | kg CO2 / short ton-mile | Source |
|------|-------------------------|--------|
| Ground (Truck) | {EMISSION_FACTORS['ground']} | EPA SmartWay |
| Air | {EMISSION_FACTORS['air']} | EPA SmartWay |

## Transport Mode Detection

Mode is determined from UPS service description:
- **Air**: Services containing keywords like "Next Day", "2nd Day", "Air", "Express", "NDA", "Saver"
- **Ground**: All other services (default)

## Order Grouping

Packages are grouped into orders using this priority:
1. **Sales Order** field (if non-blank)
2. **Tracking Number** (if Sales Order is blank)
3. **ROW-<index>** fallback (if neither is available)

Order-level emissions use:
- Total weight of all packages in order
- First available mileage estimate
- Air mode if ANY package in order shipped air

## Known Limitations

1. **Mileage is estimated**, not actual carrier routing
   - ZIP centroid distances may differ from actual addresses
   - Road factor is an approximation; actual routes vary

2. **Emissions are estimates** based on industry averages
   - Actual carrier efficiency varies by vehicle, route, load
   - Does not account for multi-stop routing optimization

3. **Zone-based fallback is less accurate** than ZIP-to-ZIP

4. **Air vs Ground detection** relies on service name parsing
   - Some edge cases may be misclassified

## Required Input Columns

| Field | Required | Notes |
|-------|----------|-------|
| Weight | Yes | Billed or package weight in pounds |
| Destination ZIP | Yes* | Required for ZIP-to-ZIP mileage |
| Zone | Fallback* | Used if ZIP unavailable |
| Service | Recommended | For air/ground mode detection |
| Tracking Number | Recommended | For order grouping |
| Sales Order | Optional | Primary order grouping field |
| Ship Date | Optional | For monthly breakdown |
| Origin ZIP | Optional | Can be set via CLI flag |

*Either Destination ZIP or Zone is required for mileage estimation.

## Exceptions

Rows are flagged as exceptions when:
- Weight is missing or invalid
- Neither ZIP-to-ZIP nor zone-based mileage could be calculated

Exception rows are preserved in output but have null emissions values.
"""

    output_path = Path(output_path)
    output_path.write_text(content, encoding="utf-8")
