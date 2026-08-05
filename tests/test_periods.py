import unittest
from datetime import date
from hvac_reports.config import ReportConfig
from hvac_reports.periods import report_period


class PeriodTests(unittest.TestCase):
    def setUp(self):
        self.config = ReportConfig()

    def test_daily_is_24_hours(self):
        period = report_period("daily", date(2026, 8, 4), self.config)
        self.assertAlmostEqual(period.hours, 24.0)

    def test_weekly_is_seven_solar_days(self):
        period = report_period("weekly", date(2026, 8, 4), self.config)
        self.assertAlmostEqual(period.hours, 168.0, places=1)

    def test_annual_begins_at_spring_boundary(self):
        period = report_period("annual", date(2026, 8, 4), self.config)
        self.assertEqual(period.start.date(), date(2026, 3, 20))

    def test_four_seasons(self):
        cases = [
            (date(2026, 4, 1), "Spring 2026"),
            (date(2026, 7, 1), "Summer 2026"),
            (date(2026, 10, 1), "Autumn 2026"),
            (date(2027, 1, 1), "Winter 2026-2027"),
        ]
        for anchor, expected in cases:
            self.assertEqual(report_period("season", anchor, self.config).label, expected)


if __name__ == "__main__":
    unittest.main()
