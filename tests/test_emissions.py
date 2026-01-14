"""Tests for emissions calculations."""

import pytest
from ups_carbon.emissions import (
    detect_transport_mode,
    calculate_ton_miles,
    calculate_kg_co2,
    calculate_emissions,
)
from ups_carbon.constants import EMISSION_FACTORS


class TestModeDetection:
    """Test transport mode detection from service strings."""

    @pytest.mark.parametrize("service,expected", [
        ("UPS Next Day Air", "air"),
        ("UPS 2nd Day Air", "air"),
        ("UPS Next Day Air Saver", "air"),
        ("UPS Express", "air"),
        ("UPS Express Saver", "air"),
        ("NDA", "air"),
        ("2DA", "air"),
        ("next day", "air"),
        ("2 day", "air"),
    ])
    def test_air_services(self, service, expected):
        """Test air services are detected."""
        assert detect_transport_mode(service) == expected

    @pytest.mark.parametrize("service,expected", [
        ("UPS Ground", "ground"),
        ("UPS Standard", "ground"),
        ("Ground", "ground"),
        ("UPS SurePost", "ground"),
        (None, "ground"),
        ("", "ground"),
    ])
    def test_ground_services(self, service, expected):
        """Test ground services are detected."""
        assert detect_transport_mode(service) == expected


class TestTonMiles:
    """Test ton-miles calculations."""

    def test_basic_calculation(self):
        """Test basic ton-miles calculation."""
        # 2000 lbs = 1 ton, 100 miles = 100 ton-miles
        ton_miles = calculate_ton_miles(2000, 100)
        assert ton_miles == 100.0

    def test_partial_ton(self):
        """Test calculation with partial ton."""
        # 500 lbs = 0.25 tons, 200 miles = 50 ton-miles
        ton_miles = calculate_ton_miles(500, 200)
        assert ton_miles == 50.0

    def test_invalid_inputs(self):
        """Test None returned for invalid inputs."""
        assert calculate_ton_miles(None, 100) is None
        assert calculate_ton_miles(100, None) is None
        assert calculate_ton_miles(-10, 100) is None


class TestKgCO2:
    """Test kg CO2 calculations."""

    def test_ground_emission(self):
        """Test ground emission calculation."""
        ton_miles = 100
        kg_co2 = calculate_kg_co2(ton_miles, "ground")
        expected = ton_miles * EMISSION_FACTORS["ground"]
        assert kg_co2 == pytest.approx(expected, rel=0.001)

    def test_air_emission(self):
        """Test air emission calculation."""
        ton_miles = 100
        kg_co2 = calculate_kg_co2(ton_miles, "air")
        expected = ton_miles * EMISSION_FACTORS["air"]
        assert kg_co2 == pytest.approx(expected, rel=0.001)

    def test_air_higher_than_ground(self):
        """Test that air emissions are higher than ground."""
        ton_miles = 100
        ground_co2 = calculate_kg_co2(ton_miles, "ground")
        air_co2 = calculate_kg_co2(ton_miles, "air")
        assert air_co2 > ground_co2

    def test_invalid_input(self):
        """Test None returned for invalid input."""
        assert calculate_kg_co2(None, "ground") is None


class TestCalculateEmissions:
    """Test complete emissions calculation."""

    def test_full_calculation(self):
        """Test complete emissions calculation."""
        result = calculate_emissions(
            weight_lb=1000,
            miles=500,
            service="UPS Ground"
        )

        assert result["mode"] == "ground"
        assert result["ton_miles"] == 250.0  # (1000/2000) * 500
        expected_co2 = 250.0 * EMISSION_FACTORS["ground"]
        assert result["kg_co2"] == pytest.approx(expected_co2, rel=0.001)

    def test_mode_override(self):
        """Test mode can be overridden."""
        result = calculate_emissions(
            weight_lb=1000,
            miles=500,
            service="UPS Ground",
            mode_override="air"
        )

        assert result["mode"] == "air"
