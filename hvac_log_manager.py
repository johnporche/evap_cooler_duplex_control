"""Fast, dependency-free log rotation for the real-time controller.

This module deliberately does not compress or summarize files. Those heavier
operations belong to ``hvac-log-maintain`` and cannot delay the control loop.
"""

import csv
from datetime import datetime
import os
from pathlib import Path


def _unique_archive_path(directory, stem, suffix, now):
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    return directory / f"{stem}-{now.strftime('%H%M%S')}{suffix}"


class _RotatingLog:
    def __init__(self, current_path, archive_prefix, maximum_bytes):
        self.current_path = Path(current_path)
        self.archive_prefix = archive_prefix
        self.maximum_bytes = int(maximum_bytes)
        self.current_path.parent.mkdir(parents=True, exist_ok=True)

    def _file_day(self, now):
        if not self.current_path.exists():
            return now.date()
        modified = datetime.fromtimestamp(self.current_path.stat().st_mtime, tz=now.tzinfo)
        return modified.date()

    def _rotation_reason(self, now):
        if not self.current_path.exists() or self.current_path.stat().st_size == 0:
            return None
        if self._file_day(now) != now.date():
            return "daily"
        if self.maximum_bytes and self.current_path.stat().st_size >= self.maximum_bytes:
            return "size"
        return None

    def _rotate(self, now, reason):
        if not self.current_path.exists() or self.current_path.stat().st_size == 0:
            return None
        day = self._file_day(now)
        directory = self.current_path.parent / "archive" / f"{day.year:04d}" / f"{day.month:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{self.archive_prefix}-{day.isoformat()}"
        if reason != "daily":
            stem += f"-{reason}"
        destination = _unique_archive_path(directory, stem, self.current_path.suffix, now)
        os.replace(str(self.current_path), str(destination))
        return destination


class RotatingCsvLog(_RotatingLog):
    def __init__(self, current_path, maximum_bytes=50 * 1024 * 1024):
        super().__init__(current_path, "hvac-state", maximum_bytes)
        self.fieldnames = None

    def ensure_header(self, fieldnames, now):
        self.fieldnames = list(fieldnames)
        reason = self._rotation_reason(now)
        if reason:
            self._rotate(now, reason)
        if self.current_path.exists() and self.current_path.stat().st_size:
            with self.current_path.open("r", newline="", encoding="utf-8") as stream:
                existing = next(csv.reader(stream), [])
            if existing != self.fieldnames:
                self._rotate(now, "schema")
        if not self.current_path.exists() or self.current_path.stat().st_size == 0:
            with self.current_path.open("w", newline="", encoding="utf-8") as stream:
                csv.DictWriter(stream, fieldnames=self.fieldnames).writeheader()

    def append(self, row, fieldnames, now):
        self.ensure_header(fieldnames, now)
        with self.current_path.open("a", newline="", encoding="utf-8") as stream:
            csv.DictWriter(stream, fieldnames=self.fieldnames).writerow(row)


class RotatingTextLog(_RotatingLog):
    def __init__(self, current_path, maximum_bytes=25 * 1024 * 1024):
        super().__init__(current_path, "hvac-events", maximum_bytes)

    def append(self, line, now):
        reason = self._rotation_reason(now)
        if reason:
            self._rotate(now, reason)
        with self.current_path.open("a", encoding="utf-8") as stream:
            stream.write(line.rstrip("\n") + "\n")

