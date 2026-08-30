#!/usr/bin/env python3
"""Wait until today's sunrise for the configured HVAC site."""

from datetime import date, datetime, timedelta, timezone
import math
import os
import time
from zoneinfo import ZoneInfo


LATITUDE = float(os.environ.get("HVAC_REPORT_LATITUDE", "39.7392"))
LONGITUDE = float(os.environ.get("HVAC_REPORT_LONGITUDE", "-104.9903"))
TIMEZONE = os.environ.get("HVAC_REPORT_TIMEZONE", "America/Denver")


def sunrise_utc(day, latitude, longitude):
    """Return sunrise using the NOAA sunrise approximation."""
    day_number = day.timetuple().tm_yday
    longitude_hour = longitude / 15.0
    approximate_time = day_number + ((6.0 - longitude_hour) / 24.0)
    mean_anomaly = (0.9856 * approximate_time) - 3.289
    true_longitude = (
        mean_anomaly
        + 1.916 * math.sin(math.radians(mean_anomaly))
        + 0.020 * math.sin(math.radians(2 * mean_anomaly))
        + 282.634
    ) % 360.0
    right_ascension = math.degrees(
        math.atan(0.91764 * math.tan(math.radians(true_longitude)))
    ) % 360.0
    right_ascension += (
        math.floor(true_longitude / 90.0) * 90.0
        - math.floor(right_ascension / 90.0) * 90.0
    )
    right_ascension /= 15.0
    sin_declination = 0.39782 * math.sin(math.radians(true_longitude))
    cos_declination = math.cos(math.asin(sin_declination))
    cos_hour = (
        math.cos(math.radians(90.833))
        - sin_declination * math.sin(math.radians(latitude))
    ) / (cos_declination * math.cos(math.radians(latitude)))
    hour_angle = (360.0 - math.degrees(math.acos(cos_hour))) / 15.0
    local_mean_time = hour_angle + right_ascension - 0.06571 * approximate_time - 6.622
    utc_hours = (local_mean_time - longitude_hour) % 24.0
    return datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=utc_hours)


def main():
    local_zone = ZoneInfo(TIMEZONE)
    now = datetime.now(local_zone)
    sunrise = sunrise_utc(now.date(), LATITUDE, LONGITUDE).astimezone(local_zone)
    delay = (sunrise - now).total_seconds()
    if delay > 0:
        time.sleep(delay)


if __name__ == "__main__":
    main()
