"""Tests for the main data processor."""

import pytest
import pandas as pd
from pathlib import Path

from ups_carbon.processor import UPSReportProcessor


# Path to test fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_CSV = FIXTURES_DIR / "sample_ups_report.csv"
MSC_CSV = FIXTURES_DIR / "monthly_shipping_costs.csv"


class TestOrderIdPriority:
    """Test order_id assignment priority: SO > Tracking > ROW-index."""

    def test_sales_order_takes_priority(self):
        """Test Sales Order is used when present."""
        df = pd.DataFrame({
            "Sales Order": ["SO-123", "SO-123"],
            "Tracking Number": [
                "1Z999AA10123456784",
                "1Z999AA10123456785"
            ],
            "Billed Weight": [5.0, 3.0],
            "Receiver Zip": ["90210", "90210"],
        })

        processor = UPSReportProcessor(origin_zip="10001")
        processor.detect_and_validate_columns(df)
        result_df, _, _ = processor.process(df)

        # Both rows should have same order_id from Sales Order
        assert result_df.iloc[0]["order_id"] == "SO-123"
        assert result_df.iloc[1]["order_id"] == "SO-123"

    def test_tracking_fallback_when_so_blank(self):
        """Test Tracking Number used when SO is blank."""
        df = pd.DataFrame({
            "Sales Order": ["", None],
            "Tracking Number": [
                "1Z999AA10123456784",
                "1Z999AA10123456785"
            ],
            "Billed Weight": [5.0, 3.0],
            "Receiver Zip": ["90210", "90210"],
        })

        processor = UPSReportProcessor(origin_zip="10001")
        processor.detect_and_validate_columns(df)
        result_df, _, _ = processor.process(df)

        # Should use tracking numbers
        assert result_df.iloc[0]["order_id"] == "1Z999AA10123456784"
        assert result_df.iloc[1]["order_id"] == "1Z999AA10123456785"

    def test_row_index_fallback(self):
        """Test ROW-index used when both SO and tracking are blank."""
        df = pd.DataFrame({
            "Sales Order": ["", ""],
            "Tracking Number": ["", ""],
            "Billed Weight": [5.0, 3.0],
            "Receiver Zip": ["90210", "90210"],
        })

        processor = UPSReportProcessor(origin_zip="10001")
        processor.detect_and_validate_columns(df)
        result_df, exceptions_df, _ = processor.process(df)

        # All rows become exceptions because they lack valid tracking
        assert len(result_df) == 0
        assert exceptions_df.iloc[0]["order_id"] == "ROW-0"
        assert exceptions_df.iloc[1]["order_id"] == "ROW-1"


class TestZoneFallback:
    """Test zone-based mileage fallback."""

    def test_zone_used_when_zip_fails(self):
        """Test zone fallback when ZIP lookup fails."""
        df = pd.DataFrame({
            "Billed Weight": [5.0],
            "Receiver Zip": ["INVALID"],
            "Zone": [5],
        })

        processor = UPSReportProcessor(origin_zip="10001")
        processor.detect_and_validate_columns(df)
        result_df, _, _ = processor.process(df)

        # Should use zone method
        assert result_df.iloc[0]["miles_method"] == "zone"
        assert result_df.iloc[0]["miles_est"] == 600  # Zone 5 default


class TestExceptionsSheet:
    """Test that exceptions are properly tracked."""

    def test_missing_weight_flagged(self):
        """Test rows with missing weight are flagged as exceptions."""
        df = pd.DataFrame({
            "Billed Weight": [None, ""],
            "Receiver Zip": ["90210", "90210"],
            "Zone": [5, 5],
        })

        processor = UPSReportProcessor(origin_zip="10001")
        processor.detect_and_validate_columns(df)
        result_df, exceptions_df, _ = processor.process(df)

        # Both rows should be exceptions
        assert len(exceptions_df) == 2
        assert exceptions_df["is_exception"].all()
        assert exceptions_df["exception_reason"].str.contains("missing_weight", na=False).all()

    def test_missing_miles_flagged(self):
        """Test rows with no mileage method are flagged as exceptions."""
        df = pd.DataFrame({
            "Billed Weight": [5.0],
            "Receiver Zip": ["INVALID"],
            # No zone column
        })

        processor = UPSReportProcessor(origin_zip="ALSO_INVALID")
        # Add zone column to pass validation
        df["Zone"] = [None]
        processor.detect_and_validate_columns(df)
        result_df, exceptions_df, _ = processor.process(df)

        # Should be exception due to missing miles
        assert len(exceptions_df) == 1
        assert "missing_miles" in exceptions_df.iloc[0]["exception_reason"]

    def test_valid_rows_not_exceptions(self):
        """Test valid rows are not flagged as exceptions."""
        df = pd.DataFrame({
            "Billed Weight": [5.0, 3.0],
            "Receiver Zip": ["90210", "10001"],
            "Zone": [5, 8],
        })

        processor = UPSReportProcessor(origin_zip="10001")
        processor.detect_and_validate_columns(df)
        result_df, exceptions_df, _ = processor.process(df)

        # No exceptions
        assert len(exceptions_df) == 0


class TestOrderRollup:
    """Test order-level rollup calculations."""

    def test_rollup_totals_match_package_sum(self):
        """Test order CO2 totals match sum of package CO2."""
        df = pd.DataFrame({
            "Sales Order": ["SO-1", "SO-1", "SO-2"],
            "Billed Weight": [10.0, 10.0, 20.0],
            "Receiver Zip": ["90210", "90210", "90210"],
            "Zone": [5, 5, 5],
            "Service Type": ["UPS Ground", "UPS Ground", "UPS Ground"],
        })

        processor = UPSReportProcessor(origin_zip="10001")
        processor.detect_and_validate_columns(df)
        result_df, _, _ = processor.process(df)
        rollup = processor.create_order_rollup(result_df)

        # Check SO-1 has 2 packages
        so1_row = rollup[rollup["order_id"] == "SO-1"].iloc[0]
        assert so1_row["packages"] == 2

        # Check total weight
        assert so1_row["total_weight_lb"] == 20.0

        # Check SO-2 has 1 package
        so2_row = rollup[rollup["order_id"] == "SO-2"].iloc[0]
        assert so2_row["packages"] == 1
        assert so2_row["total_weight_lb"] == 20.0

    def test_air_mode_if_any_package_air(self):
        """Test order mode is 'air' if any package shipped air."""
        df = pd.DataFrame({
            "Sales Order": ["SO-1", "SO-1"],
            "Billed Weight": [10.0, 10.0],
            "Receiver Zip": ["90210", "90210"],
            "Zone": [5, 5],
            "Service Type": ["UPS Ground", "UPS Next Day Air"],
        })

        processor = UPSReportProcessor(origin_zip="10001")
        processor.detect_and_validate_columns(df)
        result_df, _, _ = processor.process(df)
        rollup = processor.create_order_rollup(result_df)

        so1_row = rollup[rollup["order_id"] == "SO-1"].iloc[0]
        assert so1_row["mode_est"] == "air"


class TestSampleFixture:
    """Test processing the sample fixture CSV."""

    @pytest.fixture
    def processor(self):
        return UPSReportProcessor(origin_zip="35761")

    def test_load_sample_csv(self, processor):
        """Test sample CSV loads successfully."""
        if not SAMPLE_CSV.exists():
            pytest.skip("Sample fixture not found")

        df = processor.load_csv(SAMPLE_CSV)
        assert len(df) == 10  # 10 rows in sample

    def test_process_sample_csv(self, processor):
        """Test sample CSV processes without errors."""
        if not SAMPLE_CSV.exists():
            pytest.skip("Sample fixture not found")

        df = processor.load_csv(SAMPLE_CSV)
        processor.detect_and_validate_columns(df)
        result_df, exceptions_df, _ = processor.process(df)

        # Should have 10 rows
        assert len(result_df) == 9

        # Should have at least one exception (row 7 has missing weight)
        # Note: row 8 has empty dest_zip but has zone, so zone fallback works
        assert len(exceptions_df) >= 1

    def test_order_grouping_in_sample(self, processor):
        """Test order grouping works on sample data."""
        if not SAMPLE_CSV.exists():
            pytest.skip("Sample fixture not found")

        df = processor.load_csv(SAMPLE_CSV)
        processor.detect_and_validate_columns(df)
        result_df, _, _ = processor.process(df)
        rollup = processor.create_order_rollup(result_df)

        # SO-1001 should have 2 packages (rows 1 and 2)
        so1001 = rollup[rollup["order_id"] == "SO-1001"]
        assert len(so1001) == 1
        assert so1001.iloc[0]["packages"] == 2

        # SO-1006 should have 2 packages (rows 9 and 10)
        so1006 = rollup[rollup["order_id"] == "SO-1006"]
        assert len(so1006) == 1
        assert so1006.iloc[0]["packages"] == 2
        # Should be air mode (one package is Next Day Air Saver)
        assert so1006.iloc[0]["mode_est"] == "air"


class TestMonthlyShippingCostsFormat:
    """Test Monthly Shipping Costs CSV normalization and grouping."""

    def test_monthly_shipping_costs_grouping_and_costs(self):
        """Test grouping and cost parsing for Monthly Shipping Costs export."""
        if not MSC_CSV.exists():
            pytest.skip("Monthly Shipping Costs fixture not found")

        processor = UPSReportProcessor(origin_zip="35761")
        df = processor.load_csv(MSC_CSV)
        processor.detect_and_validate_columns(df)
        detail_df, exceptions_df, _ = processor.process(df)

        # Two valid tracking numbers in fixture
        assert len(detail_df) == 2
        assert detail_df["Tracking Number"].nunique() == 2

        row = detail_df[detail_df["Tracking Number"] == "1Z999AA10123456784"].iloc[0]
        assert row["total_cost_usd"] == pytest.approx(14.0)
        assert row["weight_lb"] == pytest.approx(5.0)
        assert row["Pickup Date"] == "2025-01-02"
        assert row["dest_zip"] == "90210"

        row2 = detail_df[detail_df["Tracking Number"] == "1Z999AA10123456785"].iloc[0]
        assert row2["origin_zip"] == "35761"

        # Invalid/blank tracking rows routed to exceptions
        assert len(exceptions_df) == 2
        assert exceptions_df["exception_reason"].str.contains("invalid_tracking", na=False).all()
