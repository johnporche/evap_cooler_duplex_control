"""Offline compression, verification, summaries, retention, and disk checks."""

import argparse
import csv
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from .config import ReportConfig
from .metrics import analyze
from .periods import ReportPeriod
from .reader import open_text, read_rows


DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _gzip_verified(path):
    path = Path(path)
    destination = Path(str(path) + ".gz")
    temporary = Path(str(destination) + ".tmp")
    if destination.exists():
        return destination
    with path.open("rb") as source, temporary.open("wb") as raw_output:
        with gzip.GzipFile(filename=path.name, mode="wb", fileobj=raw_output, compresslevel=6) as compressed:
            shutil.copyfileobj(source, compressed, length=1024 * 1024)
        raw_output.flush()
        os.fsync(raw_output.fileno())
    with gzip.open(temporary, "rb") as check:
        while check.read(1024 * 1024):
            pass
    os.replace(str(temporary), str(destination))
    path.unlink()
    return destination


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp_bounds(path):
    first = None
    last = None
    with open_text(path) as stream:
        for row in csv.DictReader(stream):
            stamp = row.get("timestamp_iso")
            if not stamp:
                continue
            try:
                value = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            first = value if first is None else min(first, value)
            last = value if last is None else max(last, value)
    return first, last


def _summary_path(log_root, archive):
    match = DATE_PATTERN.search(archive.name)
    day = datetime.fromisoformat(match.group(1)) if match else datetime.fromtimestamp(archive.stat().st_mtime)
    directory = Path(log_root) / "summaries" / f"{day.year:04d}" / f"{day.month:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    name = archive.name.removesuffix(".csv.gz").removesuffix(".csv")
    return directory / f"summary-{name}.json"


def summarize_archive(log_root, archive, config):
    destination = _summary_path(log_root, archive)
    first, last = _timestamp_bounds(archive)
    if first is None or last is None:
        return None
    period = ReportPeriod("archive", archive.name, first, last + timedelta(seconds=config.expected_sample_seconds))
    rows = read_rows([archive], period)
    metrics = analyze(rows, period, config)
    payload = {
        "schema_version": 1,
        "archive": archive.name,
        "archive_sha256": _sha256(archive),
        "archive_bytes": archive.stat().st_size,
        "first_timestamp": first.isoformat(),
        "last_timestamp": last.isoformat(),
        "generated_at": datetime.now().astimezone().isoformat(),
        "metrics": metrics.values,
        "state_hours": metrics.state_hours,
        "main_demand_hours": metrics.main_demand_hours,
        "apartment_demand_hours": metrics.apartment_demand_hours,
        "fan_target_hours": metrics.fan_target_hours,
        "daily_rows": metrics.daily_rows,
    }
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(destination))
    return destination


def _summary_for_archive(log_root, archive):
    path = _summary_path(log_root, archive)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_to_prune(summary, cutoff):
    if not summary:
        return False
    metrics = summary.get("metrics", {})
    if metrics.get("error_input_samples", 0):
        return False
    if metrics.get("static_pressure_ok_percent", 1.0) < 0.99:
        return False
    try:
        last = datetime.fromisoformat(summary["last_timestamp"])
    except (KeyError, ValueError):
        return False
    return last < cutoff


def _event_archive_day(path):
    match = DATE_PATTERN.search(Path(path).name)
    return datetime.fromisoformat(match.group(1)).astimezone() if match else None


def _event_has_fault(path):
    markers = ("SAFETY", "ERROR", " timeout", "FAULT")
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as stream:
        return any(any(marker in line for marker in markers) for line in stream)


def maintain(log_root, config, retention_days=400, event_retention_days=90, prune=False):
    root = Path(log_root)
    state_archive = root / "state" / "archive"
    event_archive = root / "events" / "archive"
    results = {"compressed": [], "summaries": [], "pruned": [], "warnings": []}
    for archive_root in (state_archive, event_archive):
        if archive_root.exists():
            for path in sorted(archive_root.rglob("*")):
                if path.is_file() and path.suffix in {".csv", ".log"}:
                    results["compressed"].append(str(_gzip_verified(path)))
    if state_archive.exists():
        for archive in sorted(state_archive.rglob("*.csv.gz")):
            summary = _summary_for_archive(root, archive)
            if not summary or summary.get("archive_sha256") != _sha256(archive):
                created = summarize_archive(root, archive, config)
                if created:
                    results["summaries"].append(str(created))
    usage = shutil.disk_usage(root)
    used_fraction = usage.used / usage.total if usage.total else 0.0
    if used_fraction >= 0.90:
        results["warnings"].append(f"CRITICAL: filesystem is {used_fraction:.1%} full")
    elif used_fraction >= 0.75:
        results["warnings"].append(f"WARNING: filesystem is {used_fraction:.1%} full")
    if prune and state_archive.exists():
        cutoff = datetime.now().astimezone() - timedelta(days=retention_days)
        for archive in sorted(state_archive.rglob("*.csv.gz")):
            summary = _summary_for_archive(root, archive)
            if _safe_to_prune(summary, cutoff):
                archive.unlink()
                results["pruned"].append(str(archive))
    if prune and event_archive.exists():
        event_cutoff = datetime.now().astimezone() - timedelta(days=event_retention_days)
        for archive in sorted(event_archive.rglob("*.log.gz")):
            day = _event_archive_day(archive)
            if day and day < event_cutoff and not _event_has_fault(archive):
                archive.unlink()
                results["pruned"].append(str(archive))
    return results


def parser():
    p = argparse.ArgumentParser(description="Compress and maintain rotated HVAC logs outside the controller process")
    p.add_argument("--log-root", default="log", help="Root containing state/, events/, and summaries/")
    p.add_argument("--config", help="Optional report configuration JSON")
    p.add_argument("--retention-days", type=int, default=400, help="State archive retention; 400 days preserves a regenerable annual report")
    p.add_argument("--event-retention-days", type=int, default=90)
    p.add_argument("--prune", action="store_true", help="Delete verified, summarized, non-fault state archives older than retention")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    config = ReportConfig.load(args.config)
    results = maintain(args.log_root, config, args.retention_days, args.event_retention_days, args.prune)
    print(f"Compressed: {len(results['compressed'])}")
    print(f"Summaries written: {len(results['summaries'])}")
    print(f"Pruned: {len(results['pruned'])}")
    for warning in results["warnings"]:
        print(warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
