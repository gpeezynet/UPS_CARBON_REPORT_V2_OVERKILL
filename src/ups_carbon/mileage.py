"""Mileage estimation using ZIP codes (pgeocode + haversine) and zone fallback."""

import math
from typing import Optional
from functools import lru_cache

import pgeocode

from .constants import DEFAULT_ZONE_MILES, DEFAULT_ROAD_FACTOR


# Global geocoder instance (lazy loaded)
_geocoder: Optional[pgeocode.Nominatim] = None


def get_geocoder() -> pgeocode.Nominatim:
    """Get or create the US geocoder instance."""
    global _geocoder
    if _geocoder is None:
        _geocoder = pgeocode.Nominatim("us")
    return _geocoder


@lru_cache(maxsize=10000)
def get_zip_coords(zip_code: str) -> Optional[tuple[float, float]]:
    """
    Get latitude/longitude for a US ZIP code.

    Args:
        zip_code: US ZIP code (5-digit or ZIP+4)

    Returns:
        Tuple of (latitude, longitude) or None if not found
    """
    if not zip_code:
        return None

    # Normalize: take first 5 digits
    zip_clean = str(zip_code).strip().replace("-", "").replace(" ", "")[:5]

    if not zip_clean.isdigit() or len(zip_clean) != 5:
        return None

    try:
        geo = get_geocoder()
        result = geo.query_postal_code(zip_clean)

        if result is None or math.isnan(result.latitude) or math.isnan(result.longitude):
            return None

        return (result.latitude, result.longitude)
    except Exception:
        return None


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two points in miles.

    Uses the haversine formula for spherical earth approximation.
    """
    R = 3958.8  # Earth's radius in miles

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def estimate_miles_zip(
    origin_zip: Optional[str],
    dest_zip: Optional[str],
    road_factor: float = DEFAULT_ROAD_FACTOR
) -> Optional[float]:
    """
    Estimate road miles between two ZIP codes.

    Args:
        origin_zip: Origin ZIP code
        dest_zip: Destination ZIP code
        road_factor: Multiplier to convert straight-line to road distance (default 1.2)

    Returns:
        Estimated road miles or None if coordinates unavailable
    """
    if not origin_zip or not dest_zip:
        return None

    origin_coords = get_zip_coords(origin_zip)
    dest_coords = get_zip_coords(dest_zip)

    if origin_coords is None or dest_coords is None:
        return None

    straight_line = haversine_miles(
        origin_coords[0], origin_coords[1],
        dest_coords[0], dest_coords[1]
    )

    return round(straight_line * road_factor, 1)


def estimate_miles_zone(
    zone: Optional[int],
    zone_miles_map: Optional[dict[int, int]] = None
) -> Optional[float]:
    """
    Estimate miles from UPS shipping zone.

    Args:
        zone: UPS zone number (2-8 typically)
        zone_miles_map: Optional custom zone-to-miles mapping

    Returns:
        Estimated miles or None if zone not in mapping
    """
    if zone is None:
        return None

    mapping = zone_miles_map or DEFAULT_ZONE_MILES

    try:
        zone_int = int(zone)
        return float(mapping.get(zone_int))
    except (ValueError, TypeError):
        return None


def estimate_miles(
    origin_zip: Optional[str],
    dest_zip: Optional[str],
    zone: Optional[int] = None,
    road_factor: float = DEFAULT_ROAD_FACTOR,
    zone_miles_map: Optional[dict[int, int]] = None
) -> tuple[Optional[float], str]:
    """
    Estimate miles using best available method.

    Priority:
    1. ZIP-to-ZIP distance (most accurate)
    2. Zone-to-miles fallback

    Args:
        origin_zip: Origin ZIP code
        dest_zip: Destination ZIP code
        zone: UPS zone (fallback)
        road_factor: Road distance multiplier
        zone_miles_map: Optional custom zone mapping

    Returns:
        Tuple of (miles_estimate, method_used)
        method_used is one of: "zip", "zone", "none"
    """
    # Try ZIP-to-ZIP first
    zip_miles = estimate_miles_zip(origin_zip, dest_zip, road_factor)
    if zip_miles is not None:
        return zip_miles, "zip"

    # Fall back to zone
    zone_miles = estimate_miles_zone(zone, zone_miles_map)
    if zone_miles is not None:
        return zone_miles, "zone"

    return None, "none"


def clear_cache():
    """Clear the ZIP coordinate cache (useful for testing)."""
    get_zip_coords.cache_clear()
