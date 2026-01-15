# UPS Carbon Report Generator

A CLI tool that generates carbon emissions estimates from UPS shipping report CSVs using a ton-mile methodology.

## Quick Start

```bash
# Install
pip install -e .

# Run
python -m ups_carbon your_ups_report.csv --out-dir ./output --origin-zip 35761
```

## Boss Spreadsheet Miles Fill

Fill the Miles column in an existing Excel workbook without changing the layout.

```bash
python tools/fill_miles_excel.py --in "C:\Georgie\WorkTools\2025_CLIMATE_REPORT_PARSED_ZIPS.xlsx" --origin-zip 35763
python tools/fill_miles_excel.py --in "C:\Georgie\WorkTools\LTL_EXPORT.xlsx" --origin-zip 35763 --out "C:\Georgie\WorkTools\LTL_EXPORT_MILES_FILLED.xlsx"
```

## Features

- **Automatic column detection** - Works with various UPS CSV formats
- **Monthly Shipping Costs support** - Normalizes UPS Monthly Shipping Costs exports
- **ZIP-to-ZIP mileage** - Uses pgeocode for distance estimation with zone fallback
- **Multi-package order support** - Groups by Sales Order, then Tracking Number
- **Comprehensive Excel reports** - Tabs: overall, by_month, by_mode, by_service, by_order, exceptions
- **Exception tracking** - Missing/invalid rows preserved and flagged

## Output Files

| File | Description |
|------|-------------|
| `*_detail.csv` | Package-level data with emissions |
| `*_report.xlsx` | Multi-tab Excel summary report |
| `ASSUMPTIONS.md` | Methodology documentation |

## Documentation

- [Full Documentation](docs/UPS_CARBON_REPORT.md)
- [Methodology & Assumptions](docs/UPS_CARBON_REPORT.md#emission-factors)

## Windows Users

Edit and run `run_report.bat` after setting your CSV path and origin ZIP.

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Emission Factors

| Mode | kg CO2 / ton-mile |
|------|-------------------|
| Ground | 0.186 |
| Air | 1.086 |
