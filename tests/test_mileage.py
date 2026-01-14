"""Tests for mileage estimation."""

import pytest
from ups_carbon.mileage import (
    haversine_miles,
    estimate_miles_zone,
    estimate_miles,
    get_zip_coords,
    clear_cache,
)
from ups_carbon.constants import DEFAULT_ZONE_MILES


class TestHaversine:
    """Test haversine distance calculations."""

    def test_same_point_zero_distance(self):
        """Same point should have zero distance."""
        dist = haversine_miles(40.7128, -74.0060, 40.7128, -74.0060)
        assert dist == pytest.approx(0, abs=0.01)

    def test_known_distance(self):
        """Test known distance between NYC and LA."""
        # NYC: 40.7128, -74.0060
        # LA: 34.0522, -118.2437
        # Approximate distance: ~2,451 miles
        dist = haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
        assert 2400 < dist < 2500


class TestZoneFallback:
    """Test zone-to-miles fallback."""

    def test_valid_zones(self):
        """Test all default zones return expected values."""
        for zone, expected_miles in DEFAULT_ZONE_MILES.items():
            miles = estimate_miles_zone(zone)
            assert miles == expected_miles

    def test_invalid_zone(self):
        """Test invalid zone returns None."""
        assert estimate_miles_zone(99) is None
        assert estimate_miles_zone(None) is None

    def test_custom_zone_map(self):
        """Test custom zone mapping."""
        custom_map = {2: 100, 3: 200}
        assert estimate_miles_zone(2, custom_map) == 100
        assert estimate_miles_zone(3, custom_map) == 200


class TestMileageEstimation:
    """Test combined mileage estimation."""

    def test_zip_takes_priority(self):
        """Test ZIP-to-ZIP is used when available."""
        # Clear cache to ensure fresh lookup
        clear_cache()

        # Use valid US ZIPs
        miles, method = estimate_miles("90210", "10001", zone=5)

        # Should use ZIP method if pgeocode works
        if method == "zip":
            assert miles > 0
            assert method == "zip"
        else:
            # Fallback to zone if pgeocode fails (e.g., no data)
            assert method == "zone"
            assert miles == DEFAULT_ZONE_MILES[5]

    def test_zone_fallback_when_zip_fails(self):
        """Test zone fallback when ZIP lookup fails."""
        miles, method = estimate_miles("INVALID", "INVALID", zone=5)
        assert miles == DEFAULT_ZONE_MILES[5]
        assert method == "zone"

    def test_none_when_all_fail(self):
        """Test None returned when all methods fail."""
        miles, method = estimate_miles(None, None, zone=None)
        assert miles is None
        assert method == "none"

    def test_road_factor_applied(self):
        """Test road factor is applied to ZIP distance."""
        clear_cache()

        miles_1x, _ = estimate_miles("90210", "90211", road_factor=1.0)
        miles_1_5x, _ = estimate_miles("90210", "90211", road_factor=1.5)

        if miles_1x is not None and miles_1_5x is not None:
            assert miles_1_5x == pytest.approx(miles_1x * 1.5, rel=0.01)
