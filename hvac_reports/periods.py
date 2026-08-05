from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import math


@dataclass(frozen=True)
class ReportPeriod:
    kind: str
    label: str
    start: datetime
    end: datetime

    @property
    def hours(self):
        return (self.end - self.start).total_seconds() / 3600.0


def approximate_solar_noon(day, latitude, longitude, timezone):
    """NOAA-style solar-noon approximation; normally within a few minutes."""
    tz = ZoneInfo(timezone)
    n = day.timetuple().tm_yday
    gamma = 2.0 * math.pi / 365.0 * (n - 1)
    eqtime = 229.18 * (
        0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma)
    )
    local_midday = datetime.combine(day, time(12), tzinfo=tz)
    offset_minutes = local_midday.utcoffset().total_seconds() / 60.0
    minutes = 720.0 - 4.0 * longitude - eqtime + offset_minutes
    return datetime.combine(day, time(0), tzinfo=tz) + timedelta(minutes=minutes)


def solar_day(day, config):
    noon = approximate_solar_noon(day, config.latitude, config.longitude, config.timezone)
    return noon - timedelta(hours=12), noon + timedelta(hours=12)


def report_period(kind, anchor, config):
    if isinstance(anchor, datetime):
        anchor = anchor.date()
    if kind == "daily":
        start, end = solar_day(anchor, config)
        return ReportPeriod(kind, anchor.isoformat(), start, end)
    if kind == "weekly":
        monday = anchor - timedelta(days=anchor.weekday())
        start = solar_day(monday, config)[0]
        end = solar_day(monday + timedelta(days=6), config)[1]
        return ReportPeriod(kind, f"Week of {monday.isoformat()}", start, end)
    if kind == "season":
        year = anchor.year
        boundaries = [
            (date(year - 1, 12, 21), date(year, 3, 20), f"Winter {year - 1}-{year}"),
            (date(year, 3, 20), date(year, 6, 20), f"Spring {year}"),
            (date(year, 6, 20), date(year, 9, 22), f"Summer {year}"),
            (date(year, 9, 22), date(year, 12, 21), f"Autumn {year}"),
            (date(year, 12, 21), date(year + 1, 3, 20), f"Winter {year}-{year + 1}"),
        ]
        start_day, end_day, label = next(item for item in boundaries if item[0] <= anchor < item[1])
        start = solar_day(start_day, config)[0]
        end = solar_day(end_day, config)[0]
        return ReportPeriod(kind, label, start, end)
    if kind == "annual":
        start_day = date(anchor.year, 3, 20)
        if anchor < start_day:
            start_day = date(anchor.year - 1, 3, 20)
        end_day = date(start_day.year + 1, 3, 20)
        start = solar_day(start_day, config)[0]
        end = solar_day(end_day, config)[0]
        return ReportPeriod(kind, f"Annual cycle spring {start_day.year} to spring {end_day.year}", start, end)
    raise ValueError("kind must be daily, weekly, season, or annual")
