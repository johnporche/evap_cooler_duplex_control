import csv
import gzip
from datetime import datetime
from pathlib import Path


NUMERIC_FIELDS = {
    "oat_calibrated_boiler_f", "therm_supply_f",
    "therm_1st_delta_from_supply_f", "therm_apt_delta_from_supply_f",
    "fan_target_speed", "fan_actual_speed", "fan_current_volts",
    "ERROR_IN", "ms1_status_raw", "ms1_status_volts", "ms1_fault_code",
    "ms1_last_high_age_seconds", "ms1_last_transition_age_seconds",
    "WWSD", "wwsd_relay_bit_6",
}
BOOLEAN_FIELDS = {
    "FRST_HEAT", "APT_HEAT", "FRST_COOL", "APT_COOL",
    "FRST_BOILER", "APT_BOILER", "boiler_panel_contact_open",
    "frst_heat_allowed", "apt_heat_allowed", "main_heat_mode_latched",
    "boiler_panel_interlock_blocked",
    "cooling_requested", "cooling_active",
    "vent_requested", "vent_active", "STATIC_PRESSURE",
    "FRST_DMP_CLOSE", "APT_DMP_CLOSE",
    "frst_cool_allowed", "apt_cool_allowed",
    "frst_vent_allowed", "apt_vent_allowed",
    "frst_air_allowed", "apt_air_allowed", "airflow_requested",
    "cooler_available", "cooler_low_oat_lockout", "ms1_power_available",
    "ms1_fault_active", "frst_cool_to_vent", "apt_cool_to_vent",
}
OPTIONAL_BOOLEAN_FIELDS = {
    "main_heat_mode_latched", "boiler_panel_interlock_blocked",
    "boiler_panel_contact_open",
}


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _boolean(value):
    return str(value).strip().lower() in {"true", "1", "yes", "on"}


def open_text(path):
    path = Path(path)
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="", encoding="utf-8")
    return path.open(newline="", encoding="utf-8")


def discover_log_paths(log_dir):
    root = Path(log_dir)
    state_root = root / "state" if (root / "state").is_dir() else root
    paths = []
    for pattern in ("current.csv", "hvac-state-*.csv", "hvac-state-*.csv.gz"):
        paths.extend(state_root.rglob(pattern))
    # Keep pre-rotation logs discoverable during migration to state/current.csv.
    for pattern in ("hvac_state_log*.csv", "hvac_state_log*.csv.gz"):
        paths.extend(root.glob(pattern))
    return sorted({path.resolve() for path in paths if path.is_file()})


def read_rows(paths, period):
    rows = []
    for path in paths:
        with open_text(path) as stream:
            for row in csv.DictReader(stream):
                stamp = row.get("timestamp_iso")
                if not stamp:
                    continue
                try:
                    timestamp = datetime.fromisoformat(stamp)
                except ValueError:
                    continue
                if timestamp < period.start or timestamp >= period.end:
                    continue
                parsed = dict(row)
                parsed["timestamp"] = timestamp
                for field in NUMERIC_FIELDS:
                    parsed[field] = _number(row.get(field))
                for field in BOOLEAN_FIELDS:
                    value = row.get(field)
                    parsed[field] = (
                        None
                        if field in OPTIONAL_BOOLEAN_FIELDS and value in (None, "")
                        else _boolean(value)
                    )
                rows.append(parsed)
    rows.sort(key=lambda item: item["timestamp"])
    deduplicated = []
    last_stamp = None
    for row in rows:
        if row["timestamp"] != last_stamp:
            deduplicated.append(row)
            last_stamp = row["timestamp"]
    return deduplicated
