# UPS Carbon Report Generator

A command-line tool that processes UPS shipping report CSVs and generates carbon emissions estimates using a ton-mile methodology.

## Features

- **Automatic column detection**: Works with various UPS CSV formats
- **Monthly Shipping Costs support**: Normalizes UPS Monthly Shipping Costs exports
- **ZIP-to-ZIP mileage**: Uses pgeocode for accurate distance estimation
- **Zone fallback**: Falls back to zone-based estimates when ZIP unavailable
- **Multi-package order support**: Groups packages by Sales Order or Tracking Number
- **Comprehensive Excel reports**: Multiple summary tabs for analysis
- **Exception tracking**: Preserves and flags rows with missing data

## Installation

```bash
# From the repository root
pip install -e .

# Or install dependencies directly
pip install pandas openpyxl pgeocode click
```

## Quick Start

```bash
# Basic usage
python -m ups_carbon path/to/ups_report.csv

# With origin ZIP and custom output directory
python -m ups_carbon report.csv --out-dir ./output --origin-zip 35761

# Windows: Edit and run the batch file
run_report.bat
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `CSV_PATH` | Path to UPS shipping CSV (required) |
| `--out-dir, -o` | Output directory (default: `<csv_name>_carbon_output/`) |
| `--origin-zip` | Default origin ZIP code |
| `--road-factor` | Haversine to road distance multiplier (default: 1.2) |
| `--col-weight` | Override weight column name |
| `--col-dest-zip` | Override destination ZIP column name |
| `--col-origin-zip` | Override origin ZIP column name |
| `--col-service` | Override service type column name |
| `--col-tracking` | Override tracking number column name |
| `--col-zone` | Override zone column name |
| `--col-sales-order` | Override sales order column name |
| `--verbose, -v` | Show detailed output |

## Input CSV Requirements

### Required Columns

| Column | Auto-detected Names |
|--------|---------------------|
| Weight | "Billed Weight", "Package Weight", "Weight (lb)" |
| Destination ZIP *or* Zone | "Receiver Zip", "Dest Zip", "Zone" |

### Recommended Columns

| Column | Auto-detected Names |
|--------|---------------------|
| Service | "Service Type", "Service Description", "Service" |
| Tracking | "Tracking Number", "Package Tracking" |
| Sales Order | "Sales Order", "SO", "Order Number", "Reference Number 1/2/3" |
| Ship Date | "Ship Date", "Pickup Date", "Shipped Date" |
| Origin ZIP | "Sender Zip", "Origin Zip", "Ship From Zip" |

### Monthly Shipping Costs Export

The UPS **Monthly Shipping Costs** CSV export is supported and auto-normalized.
Required columns:

- Tracking Number
- Pickup Date
- Service Level
- Weight
- Receiver Zip Code
- Reference No.1
- Billed Charge
- Incentive Credit

Optional:
- Sender Zip Code (used for origin ZIP)

## Output Files

### 1. `<base>_detail.csv`

Package-level detail with calculated fields:
- `order_id`: Assigned order identifier
- `miles_est`: Estimated miles
- `miles_method`: "zip" or "zone"
- `mode_est`: "air" or "ground"
- `ton_miles`: (weight_lb / 2000) * miles
- `kg_co2_est`: ton_miles * emission_factor
- `is_exception`: True if data missing
- `exception_reason`: What's missing

### 2. `<base>_report.xlsx`

Excel workbook with tabs:

| Tab | Contents |
|-----|----------|
| `overall` | Summary statistics |
| `by_month` | Monthly breakdown |
| `by_mode` | Air vs Ground breakdown |
| `by_service` | By UPS service type |
| `by_order` | Order-level rollup with aggregated emissions |
| `exceptions` | Rows with missing/invalid data |

### 3. `ASSUMPTIONS.md`

Documents the methodology, emission factors, and limitations.

## Order Grouping Logic

Packages are grouped into orders using this priority:

1. **Sales Order** (SO): If non-blank, use as order_id
2. **Tracking Number**: If SO blank but tracking exists
3. **ROW-<index>**: Fallback for rows with neither

Order-level emissions (`by_order` tab) calculate:
- Total weight across packages
- Mode: "air" if ANY package is air
- Miles: First non-null estimate
- `miles_inconsistent` flag if estimates differ

## Emission Factors

| Mode | kg CO2 / ton-mile | Source |
|------|-------------------|--------|
| Ground | 0.186 | EPA SmartWay |
| Air | 1.086 | EPA SmartWay |

## Troubleshooting

### "Missing required columns" error

The tool couldn't find weight and/or destination ZIP/zone columns.

**Solutions:**
1. Check CSV column headers match expected patterns
2. Use `--col-weight "Your Column Name"` to specify manually
3. Ensure CSV isn't corrupted or has unusual encoding

### High exception count

Many rows flagged as exceptions usually means:
- Missing destination ZIP *and* zone columns
- Weight column has empty/invalid values

### Mileage seems wrong

- ZIP-to-ZIP uses centroid distances (approximation)
- Zone fallback uses fixed distance estimates
- Check `miles_method` column in detail output

## Examples

### Process with column overrides

```bash
python -m ups_carbon data.csv \
  --col-weight "Billed Wt (lb)" \
  --col-dest-zip "Ship To Postal" \
  --col-sales-order "Customer PO"
```

### Process multiple months

```bash
# Process each file separately
for file in monthly_reports/*.csv; do
  python -m ups_carbon "$file" --out-dir "./output/$(basename "$file" .csv)"
done
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run specific test
pytest tests/test_processor.py::test_order_id_priority -v
```
