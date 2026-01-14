"""Constants for emissions calculations and zone mappings."""

# CO2 emission factors in kg CO2 per short ton-mile
# Sources: EPA SmartWay, carrier sustainability reports
EMISSION_FACTORS = {
    "ground": 0.186,  # kg CO2 / short ton-mile (truck freight)
    "air": 1.086,     # kg CO2 / short ton-mile (air freight)
}

# Default zone-to-miles mapping (approximate midpoint distances)
# Zone represents shipping zones used by UPS for pricing
DEFAULT_ZONE_MILES = {
    2: 50,
    3: 150,
    4: 300,
    5: 600,
    6: 1000,
    7: 1400,
    8: 1800,
}

# Road factor: multiplier to convert haversine (straight-line) distance to road distance
DEFAULT_ROAD_FACTOR = 1.2

# Tokens that indicate air shipping (case-insensitive matching)
AIR_SERVICE_TOKENS = [
    "next day",
    "2nd day",
    "2 day",
    "air",
    "express",
    "nda",
    "2da",
    "saver",
    "overnight",
    "priority",
]

# Pounds per short ton
LBS_PER_TON = 2000
