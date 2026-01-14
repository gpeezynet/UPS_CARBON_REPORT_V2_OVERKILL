"""Tests for column auto-detection."""

import pytest
from ups_carbon.columns import detect_columns, validate_required_columns, ColumnMapping


class TestColumnDetection:
    """Test column auto-detection."""

    def test_detect_standard_columns(self):
        """Test detection of standard UPS column names."""
        columns = [
            "Ship Date",
            "Tracking Number",
            "Service Type",
            "Billed Weight",
            "Receiver Zip",
            "Zone",
            "Sales Order",
        ]
        mapping = detect_columns(columns)

        assert mapping.ship_date == "Ship Date"
        assert mapping.tracking == "Tracking Number"
        assert mapping.service == "Service Type"
        assert mapping.weight == "Billed Weight"
        assert mapping.dest_zip == "Receiver Zip"
        assert mapping.zone == "Zone"
        assert mapping.sales_order == "Sales Order"

    def test_detect_alternate_names(self):
        """Test detection of alternate column names."""
        columns = [
            "Pickup Date",
            "Package Weight",
            "Dest Zip",
            "Shipping Zone",
            "SO",
        ]
        mapping = detect_columns(columns)

        assert mapping.ship_date == "Pickup Date"
        assert mapping.weight == "Package Weight"
        assert mapping.dest_zip == "Dest Zip"
        assert mapping.zone == "Shipping Zone"
        assert mapping.sales_order == "SO"

    def test_detect_reference_as_sales_order(self):
        """Test that Reference Number columns are detected as sales order."""
        columns = ["Reference Number 1", "Weight"]
        mapping = detect_columns(columns)
        assert mapping.sales_order == "Reference Number 1"

    def test_overrides_take_precedence(self):
        """Test that CLI overrides take precedence over auto-detection."""
        columns = ["Billed Weight", "Package Weight"]
        overrides = {"weight": "Package Weight"}
        mapping = detect_columns(columns, overrides)

        assert mapping.weight == "Package Weight"

    def test_validate_required_with_weight_and_zip(self):
        """Test validation passes with required columns."""
        mapping = ColumnMapping(weight="Weight", dest_zip="Zip")
        is_valid, missing = validate_required_columns(mapping)
        assert is_valid is True
        assert len(missing) == 0

    def test_validate_required_with_weight_and_zone(self):
        """Test validation passes with weight and zone (fallback)."""
        mapping = ColumnMapping(weight="Weight", zone="Zone")
        is_valid, missing = validate_required_columns(mapping)
        assert is_valid is True

    def test_validate_fails_without_weight(self):
        """Test validation fails without weight column."""
        mapping = ColumnMapping(dest_zip="Zip")
        is_valid, missing = validate_required_columns(mapping)
        assert is_valid is False
        assert any("weight" in m.lower() for m in missing)

    def test_validate_fails_without_zip_or_zone(self):
        """Test validation fails without both ZIP and zone."""
        mapping = ColumnMapping(weight="Weight")
        is_valid, missing = validate_required_columns(mapping)
        assert is_valid is False
        assert any("zip" in m.lower() or "zone" in m.lower() for m in missing)
