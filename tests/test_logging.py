import csv
from datetime import datetime, timedelta
import gzip
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from hvac_log_manager import RotatingCsvLog, RotatingTextLog
from hvac_reports.reader import discover_log_paths, read_rows
from hvac_reports.periods import ReportPeriod


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tz = ZoneInfo("America/Denver")

    def tearDown(self):
        self.temp.cleanup()

    def test_csv_rotates_at_new_local_day(self):
        logger = RotatingCsvLog(self.root / "state" / "current.csv", maximum_bytes=100000)
        fields = ["timestamp_iso", "value"]
        first = datetime(2026, 8, 4, 23, 59, tzinfo=self.tz)
        second = first + timedelta(minutes=2)
        logger.append({"timestamp_iso": first.isoformat(), "value": 1}, fields, first)
        logger.append({"timestamp_iso": second.isoformat(), "value": 2}, fields, second)
        archives = list((self.root / "state" / "archive").rglob("*.csv"))
        self.assertEqual(len(archives), 1)
        self.assertIn("2026-08-04", archives[0].name)
        with (self.root / "state" / "current.csv").open() as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 1)

    def test_text_rotates_by_size(self):
        logger = RotatingTextLog(self.root / "events" / "current.log", maximum_bytes=5)
        now = datetime(2026, 8, 4, 12, tzinfo=self.tz)
        logger.append("12345", now)
        logger.append("next", now)
        self.assertEqual(len(list((self.root / "events" / "archive").rglob("*.log"))), 1)

    def test_reader_discovers_and_reads_gzip(self):
        state = self.root / "state" / "archive" / "2026" / "08"
        state.mkdir(parents=True)
        path = state / "hvac-state-2026-08-04.csv.gz"
        stamp = datetime(2026, 8, 4, 12, tzinfo=self.tz)
        with gzip.open(path, "wt", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["timestamp_iso", "fan_actual_speed"])
            writer.writeheader(); writer.writerow({"timestamp_iso": stamp.isoformat(), "fan_actual_speed": 2})
        paths = discover_log_paths(self.root)
        self.assertEqual(paths, [path.resolve()])
        period = ReportPeriod("test", "test", stamp - timedelta(minutes=1), stamp + timedelta(minutes=1))
        self.assertEqual(len(read_rows(paths, period)), 1)


if __name__ == "__main__":
    unittest.main()

