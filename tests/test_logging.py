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
        today = datetime.now(self.tz).date()
        first = datetime.combine(today, datetime.min.time(), tzinfo=self.tz) + timedelta(hours=23, minutes=59)
        second = first + timedelta(minutes=2)
        logger.append({"timestamp_iso": first.isoformat(), "value": 1}, fields, first)
        logger.append({"timestamp_iso": second.isoformat(), "value": 2}, fields, second)
        archives = list((self.root / "state" / "archive").rglob("*.csv"))
        self.assertEqual(len(archives), 1)
        self.assertIn(first.date().isoformat(), archives[0].name)
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

    def test_reader_keeps_ms1_voltage_numeric_and_fault_boolean(self):
        path = self.root / "current.csv"
        stamp = datetime(2026, 8, 4, 12, tzinfo=self.tz)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=["timestamp_iso", "ERROR_IN", "ms1_status_volts", "ms1_fault_active"],
            )
            writer.writeheader()
            writer.writerow({
                "timestamp_iso": stamp.isoformat(),
                "ERROR_IN": "10682",
                "ms1_status_volts": "10.682",
                "ms1_fault_active": "False",
            })
        period = ReportPeriod("test", "test", stamp - timedelta(minutes=1), stamp + timedelta(minutes=1))

        row = read_rows([path], period)[0]

        self.assertEqual(row["ERROR_IN"], 10682.0)
        self.assertEqual(row["ms1_status_volts"], 10.682)
        self.assertFalse(row["ms1_fault_active"])

    def test_reader_preserves_new_heat_interlock_states_and_legacy_unknowns(self):
        path = self.root / "current.csv"
        stamp = datetime(2026, 8, 4, 12, tzinfo=self.tz)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "timestamp_iso", "FRST_HEAT", "frst_heat_allowed",
                    "main_heat_mode_latched", "boiler_panel_interlock_blocked",
                ],
            )
            writer.writeheader()
            writer.writerow({
                "timestamp_iso": stamp.isoformat(),
                "FRST_HEAT": "True",
                "frst_heat_allowed": "True",
                "main_heat_mode_latched": "True",
                "boiler_panel_interlock_blocked": "False",
            })
            writer.writerow({"timestamp_iso": (stamp + timedelta(seconds=5)).isoformat()})
        period = ReportPeriod("test", "test", stamp - timedelta(minutes=1), stamp + timedelta(minutes=1))

        current, legacy = read_rows([path], period)

        self.assertTrue(current["FRST_HEAT"])
        self.assertTrue(current["frst_heat_allowed"])
        self.assertTrue(current["main_heat_mode_latched"])
        self.assertFalse(current["boiler_panel_interlock_blocked"])
        self.assertIsNone(legacy["main_heat_mode_latched"])
        self.assertIsNone(legacy["boiler_panel_interlock_blocked"])


if __name__ == "__main__":
    unittest.main()
