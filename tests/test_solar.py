"""Tests for bayesian_studio.engine.solar — ported from backfill."""
from datetime import datetime, timezone

from bayesian_studio.engine.solar import solar_elevation


class TestSolarElevation:
    def test_midnight_utc_is_below_horizon(self):
        # Midnight UTC at London — sun is below horizon
        dt = datetime(2024, 6, 21, 0, 0, 0, tzinfo=timezone.utc)
        ts = dt.timestamp()
        elev = solar_elevation(ts, 51.5, -0.1)
        assert elev < 0

    def test_noon_utc_london_summer_is_above_horizon(self):
        dt = datetime(2024, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        ts = dt.timestamp()
        elev = solar_elevation(ts, 51.5, -0.1)
        assert elev > 30

    def test_equatorial_noon_approaches_90(self):
        # At equator on equinox, solar elevation at solar noon ≈ 90°
        dt = datetime(2024, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
        ts = dt.timestamp()
        elev = solar_elevation(ts, 0.0, 0.0)
        assert elev > 80

    def test_returns_float(self):
        dt = datetime(2024, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        elev = solar_elevation(dt.timestamp(), 51.5, -0.1)
        assert isinstance(elev, float)

    def test_winter_noon_lower_than_summer(self):
        summer = datetime(2024, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        winter = datetime(2024, 12, 21, 12, 0, 0, tzinfo=timezone.utc)
        assert solar_elevation(summer.timestamp(), 51.5, -0.1) > \
               solar_elevation(winter.timestamp(), 51.5, -0.1)
