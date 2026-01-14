"""CO2 emissions calculations based on ton-miles methodology."""

import re
from typing import Optional

from .constants import EMISSION_FACTORS, AIR_SERVICE_TOKENS, LBS_PER_TON


def detect_transport_mode(service: Optional[str]) -> str:
    """
    Detect transport mode (air or ground) from UPS service description.

    Args:
        service: UPS service type string (e.g., "UPS Next Day Air", "UPS Ground")

    Returns:
        "air" or "ground"
    """
    if not service:
        return "ground"

    service_lower = service.lower()

    for token in AIR_SERVICE_TOKENS:
        # Use word boundary matching to avoid false positives
        # e.g., "nda" should not match "standard"
        pattern = r'\b' + re.escape(token) + r'\b'
        if re.search(pattern, service_lower):
            return "air"

    return "ground"


def calculate_ton_miles(weight_lb: Optional[float], miles: Optional[float]) -> Optional[float]:
    """
    Calculate ton-miles from weight and distance.

    Args:
        weight_lb: Package weight in pounds
        miles: Distance in miles

    Returns:
        Ton-miles (short tons) or None if inputs invalid
    """
    if weight_lb is None or miles is None:
        return None

    try:
        weight = float(weight_lb)
        dist = float(miles)

        if weight <= 0 or dist < 0:
            return None

        return (weight / LBS_PER_TON) * dist
    except (ValueError, TypeError):
        return None


def calculate_kg_co2(
    ton_miles: Optional[float],
    mode: str,
    emission_factors: Optional[dict[str, float]] = None
) -> Optional[float]:
    """
    Calculate kg CO2 emissions from ton-miles.

    Args:
        ton_miles: Ton-miles value
        mode: Transport mode ("air" or "ground")
        emission_factors: Optional custom emission factors

    Returns:
        kg CO2 or None if inputs invalid
    """
    if ton_miles is None:
        return None

    factors = emission_factors or EMISSION_FACTORS
    factor = factors.get(mode, factors["ground"])

    try:
        return round(float(ton_miles) * factor, 4)
    except (ValueError, TypeError):
        return None


def calculate_emissions(
    weight_lb: Optional[float],
    miles: Optional[float],
    service: Optional[str] = None,
    mode_override: Optional[str] = None,
    emission_factors: Optional[dict[str, float]] = None
) -> dict:
    """
    Calculate complete emissions data for a package.

    Args:
        weight_lb: Package weight in pounds
        miles: Estimated distance in miles
        service: UPS service description (for mode detection)
        mode_override: Force a specific mode ("air" or "ground")
        emission_factors: Optional custom emission factors

    Returns:
        Dict with keys: mode, ton_miles, kg_co2
    """
    mode = mode_override if mode_override else detect_transport_mode(service)
    ton_miles = calculate_ton_miles(weight_lb, miles)
    kg_co2 = calculate_kg_co2(ton_miles, mode, emission_factors)

    return {
        "mode": mode,
        "ton_miles": ton_miles,
        "kg_co2": kg_co2,
    }
