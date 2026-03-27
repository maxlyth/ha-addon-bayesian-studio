"""Solar elevation computation — no external dependencies."""

import math
from datetime import datetime, timezone


def solar_elevation(ts: float, lat_deg: float, lon_deg: float) -> float:
    """Compute solar elevation angle in degrees at a given Unix timestamp and location.

    Uses the Spencer equation for declination and an equation-of-time correction.
    Accurate to ~1 deg — sufficient for the >5 deg threshold used in Bayesian templates.
    """
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    n = dt.timetuple().tm_yday
    B = math.radians(360 / 365 * (n - 81))
    decl = math.radians(23.45 * math.sin(B))
    eot = 9.87 * math.sin(2 * B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)
    solar_time = dt.hour + dt.minute / 60 + dt.second / 3600 + lon_deg / 15 + eot / 60
    hour_angle = math.radians(15 * (solar_time - 12))
    lat = math.radians(lat_deg)
    return math.degrees(
        math.asin(
            math.sin(lat) * math.sin(decl)
            + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)
        )
    )
