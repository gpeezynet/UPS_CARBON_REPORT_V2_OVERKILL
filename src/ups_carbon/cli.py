"""Command-line interface for UPS Carbon Report Generator."""

import sys
from pathlib import Path

import click
import pandas as pd

from .processor import UPSReportProcessor
from .report import generate_excel_report, generate_assumptions_md
from .columns import get_column_detection_report
from .constants import DEFAULT_ROAD_FACTOR, DEFAULT_ZONE_MILES


@click.command()
@click.argument("csv_path", type=click.Path(exists=True))
@click.option(
    "--out-dir", "-o",
    type=click.Path(),
    default=None,
    help="Output directory (default: same as input file)"
)
@click.option(
    "--origin-zip",
    type=str,
    default=None,
    help="Default origin ZIP code (used if not in data)"
)
@click.option(
    "--road-factor",
    type=float,
    default=DEFAULT_ROAD_FACTOR,
    help=f"Road distance multiplier (default: {DEFAULT_ROAD_FACTOR})"
)
@click.option(
    "--col-weight",
    type=str,
    default=None,
    help="Override: weight column name"
)
@click.option(
    "--col-dest-zip",
    type=str,
    default=None,
    help="Override: destination ZIP column name"
)
@click.option(
    "--col-origin-zip",
    type=str,
    default=None,
    help="Override: origin ZIP column name"
)
@click.option(
    "--col-service",
    type=str,
    default=None,
    help="Override: service type column name"
)
@click.option(
    "--col-tracking",
    type=str,
    default=None,
    help="Override: tracking number column name"
)
@click.option(
    "--col-zone",
    type=str,
    default=None,
    help="Override: zone column name"
)
@click.option(
    "--col-sales-order",
    type=str,
    default=None,
    help="Override: sales order column name"
)
@click.option(
    "--col-ship-date",
    type=str,
    default=None,
    help="Override: ship date column name"
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show detailed output"
)
def main(
    csv_path: str,
    out_dir: str,
    origin_zip: str,
    road_factor: float,
    col_weight: str,
    col_dest_zip: str,
    col_origin_zip: str,
    col_service: str,
    col_tracking: str,
    col_zone: str,
    col_sales_order: str,
    col_ship_date: str,
    verbose: bool,
):
    """
    Generate carbon emissions report from UPS shipping CSV.

    CSV_PATH: Path to the UPS shipping report CSV file.

    Example:
        python -m ups_carbon report.csv --out-dir ./output --origin-zip 35761
    """
    csv_path = Path(csv_path)
    click.echo(f"Processing: {csv_path.name}")

    # Determine output directory
    if out_dir:
        output_dir = Path(out_dir)
    else:
        output_dir = csv_path.parent / f"{csv_path.stem}_carbon_output"

    output_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"Output directory: {output_dir}")

    # Build column overrides
    column_overrides = {}
    if col_weight:
        column_overrides["weight"] = col_weight
    if col_dest_zip:
        column_overrides["dest_zip"] = col_dest_zip
    if col_origin_zip:
        column_overrides["origin_zip"] = col_origin_zip
    if col_service:
        column_overrides["service"] = col_service
    if col_tracking:
        column_overrides["tracking"] = col_tracking
    if col_zone:
        column_overrides["zone"] = col_zone
    if col_sales_order:
        column_overrides["sales_order"] = col_sales_order
    if col_ship_date:
        column_overrides["ship_date"] = col_ship_date

    # Initialize processor
    processor = UPSReportProcessor(
        origin_zip=origin_zip,
        road_factor=road_factor,
        column_overrides=column_overrides,
    )

    # Load CSV
    try:
        df = processor.load_csv(csv_path)
        click.echo(f"Loaded {len(df)} rows")
    except Exception as e:
        click.echo(f"Error loading CSV: {e}", err=True)
        sys.exit(1)

    # Detect columns
    try:
        mapping = processor.detect_and_validate_columns(df)
        if verbose:
            click.echo("\n" + get_column_detection_report(mapping))
    except ValueError as e:
        click.echo(f"\nError: {e}", err=True)
        sys.exit(1)

    # Process data
    click.echo("Calculating mileage and emissions...")
    detail_df, exceptions = processor.process(df)

    # Create order rollup
    click.echo("Creating order-level rollup...")
    order_rollup = processor.create_order_rollup(detail_df)

    # Output file paths
    base_name = csv_path.stem
    detail_path = output_dir / f"{base_name}_detail.csv"
    report_path = output_dir / f"{base_name}_report.xlsx"
    assumptions_path = output_dir / "ASSUMPTIONS.md"

    # Save detail CSV
    click.echo(f"Writing detail CSV: {detail_path.name}")
    # Select output columns
    output_cols = [
        "order_id", "_original_index"
    ]
    # Add original columns
    for col in df.columns:
        if col not in output_cols:
            output_cols.append(col)
    # Add calculated columns
    calc_cols = [
        "weight_lb", "origin_zip", "dest_zip", "zone", "service",
        "miles_est", "miles_method", "mode_est", "ton_miles", "kg_co2_est",
        "is_exception", "exception_reason"
    ]
    for col in calc_cols:
        if col not in output_cols and col in detail_df.columns:
            output_cols.append(col)

    detail_df[[c for c in output_cols if c in detail_df.columns]].to_csv(
        detail_path, index=False
    )

    # Generate Excel report
    click.echo(f"Writing Excel report: {report_path.name}")
    generate_excel_report(
        detail_df, order_rollup, report_path,
        input_filename=csv_path.name
    )

    # Generate ASSUMPTIONS.md
    click.echo(f"Writing assumptions: {assumptions_path.name}")
    generate_assumptions_md(
        assumptions_path,
        origin_zip=origin_zip,
        road_factor=road_factor,
    )

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("SUMMARY")
    click.echo("=" * 50)
    click.echo(f"Total packages: {len(detail_df)}")
    click.echo(f"Unique orders: {detail_df['order_id'].nunique()}")

    total_co2 = detail_df["kg_co2_est"].sum()
    if pd.notna(total_co2):
        click.echo(f"Total kg CO2 (est): {total_co2:,.2f}")
        click.echo(f"Total metric tons CO2: {total_co2/1000:,.4f}")

    click.echo(f"Exceptions: {len(exceptions)}")

    if len(exceptions) > 0:
        click.echo(f"\nWarning: {len(exceptions)} rows have missing data (see exceptions tab)")

    click.echo("\n" + "=" * 50)
    click.echo("OUTPUT FILES")
    click.echo("=" * 50)
    click.echo(f"  {detail_path}")
    click.echo(f"  {report_path}")
    click.echo(f"  {assumptions_path}")

    click.echo("\nDone!")


if __name__ == "__main__":
    main()
