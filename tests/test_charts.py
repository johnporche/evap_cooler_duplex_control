import unittest
from datetime import datetime, timedelta, timezone

from hvac_reports.charts import _damper_state_intervals, _solar_markers
from hvac_reports.periods import ReportPeriod


class DamperChartTests(unittest.TestCase):
    def test_separates_closed_idle_open_and_requested_open(self):
        start = datetime(2026, 8, 4, tzinfo=timezone.utc)
        period = ReportPeriod("daily", "test", start, start + timedelta(hours=1))
        rows = [
            {"timestamp": start, "FRST_DMP_CLOSE": True, "frst_air_allowed": False},
            {"timestamp": start + timedelta(seconds=5), "FRST_DMP_CLOSE": False, "frst_air_allowed": False},
            {"timestamp": start + timedelta(seconds=10), "FRST_DMP_CLOSE": False, "frst_air_allowed": True},
            {"timestamp": start + timedelta(seconds=15), "FRST_DMP_CLOSE": True, "frst_air_allowed": False},
        ]

        idle_open, active_open = _damper_state_intervals(
            rows, period, "FRST_DMP_CLOSE", "frst_air_allowed"
        )

        self.assertEqual(idle_open, [(5 / 3600, 10 / 3600)])
        self.assertEqual(active_open, [(10 / 3600, 15 / 3600)])

    def test_builds_sunrise_noon_and_sunset_markers_from_log(self):
        start = datetime(2026, 8, 4, tzinfo=timezone.utc)
        period = ReportPeriod("daily", "test", start, start + timedelta(days=1))
        rows = [{
            "timestamp": start,
            "sunrise_local": "2026-08-04T06:00:00+00:00",
            "sunset_local": "2026-08-04T20:00:00+00:00",
        }]

        markers = _solar_markers(rows, period)

        self.assertEqual([item[:3] for item in markers], [
            ("Sunrise", 6.0, "06:00"),
            ("Solar noon", 13.0, "13:00"),
            ("Sunset", 20.0, "20:00"),
        ])


if __name__ == "__main__":
    unittest.main()
