from dataclasses import dataclass
from datetime import timedelta
from statistics import mean, median


@dataclass
class Metrics:
    values: dict
    state_hours: dict
    main_demand_hours: dict
    apartment_demand_hours: dict
    fan_target_hours: dict
    daily_rows: list


def _finite(rows, field, predicate=lambda row: True):
    return [row[field] for row in rows if predicate(row) and row.get(field) is not None]


def _episodes(rows, field):
    count = 0
    active = False
    durations = []
    start = None
    for row in rows:
        value = bool(row.get(field))
        if value and not active:
            count += 1
            start = row["timestamp"]
        elif active and not value and start is not None:
            durations.append((row["timestamp"] - start).total_seconds() / 60.0)
            start = None
        active = value
    if active and start is not None and rows:
        durations.append((rows[-1]["timestamp"] - start).total_seconds() / 60.0)
    return count, durations


def analyze(rows, period, config):
    state_seconds = {}
    main_seconds = {}
    apt_seconds = {}
    fan_seconds = {}
    observed_seconds = 0.0
    day_seconds = {}
    main_heat_seconds = 0.0
    apt_heat_seconds = 0.0
    heat_mode_seconds = 0.0
    auxiliary_heat_enable_seconds = 0.0
    for current, following in zip(rows, rows[1:]):
        delta = (following["timestamp"] - current["timestamp"]).total_seconds()
        if delta <= 0 or delta > config.maximum_sample_gap_seconds:
            continue
        observed_seconds += delta
        state = current.get("bms_state") or "UNKNOWN"
        main = current.get("frst_demand_level") or "OFF"
        apt = current.get("apt_demand_level") or "OFF"
        fan = str(int(round(current.get("fan_target_speed") or 0)))
        state_seconds[state] = state_seconds.get(state, 0.0) + delta
        main_seconds[main] = main_seconds.get(main, 0.0) + delta
        apt_seconds[apt] = apt_seconds.get(apt, 0.0) + delta
        fan_seconds[fan] = fan_seconds.get(fan, 0.0) + delta
        day = current["timestamp"].date().isoformat()
        bucket = day_seconds.setdefault(day, {"observed": 0.0, "cooling": 0.0, "vent": 0.0, "main_heat": 0.0, "apt_heat": 0.0})
        bucket["observed"] += delta
        if current.get("cooling_active"):
            bucket["cooling"] += delta
        if current.get("vent_active"):
            bucket["vent"] += delta
        if current.get("frst_heat_allowed"):
            main_heat_seconds += delta
            bucket["main_heat"] += delta
        if current.get("apt_heat_allowed"):
            apt_heat_seconds += delta
            bucket["apt_heat"] += delta
        if current.get("main_heat_mode_latched"):
            heat_mode_seconds += delta
        if current.get("boiler_panel_interlock_blocked") is False:
            auxiliary_heat_enable_seconds += delta

    main_calls, main_durations = _episodes(rows, "FRST_COOL")
    apt_calls, apt_durations = _episodes(rows, "APT_COOL")
    cooling_starts, _ = _episodes(rows, "cooling_active")
    vent_cycles, _ = _episodes(rows, "vent_active")
    main_heat_calls, main_heat_durations = _episodes(rows, "FRST_HEAT")
    apt_heat_calls, apt_heat_durations = _episodes(rows, "APT_HEAT")
    fan_errors = [abs(a - b) for a, b in zip(
        _finite(rows, "fan_target_speed"), _finite(rows, "fan_actual_speed")
    )]
    active_supply = _finite(rows, "therm_supply_f", lambda row: row.get("cooling_active"))
    oats = _finite(rows, "oat_calibrated_boiler_f")
    ms1_rows = [row for row in rows if row.get("ms1_state")]
    values = {
        "period_hours": period.hours,
        "observed_hours": observed_seconds / 3600.0,
        "coverage": observed_seconds / (period.hours * 3600.0) if period.hours else 0.0,
        "rows": len(rows),
        "cooling_starts": cooling_starts,
        "vent_cycles": vent_cycles,
        "main_heat_calls": main_heat_calls,
        "apartment_heat_calls": apt_heat_calls,
        "main_median_heat_minutes": median(main_heat_durations) if main_heat_durations else 0.0,
        "apartment_median_heat_minutes": median(apt_heat_durations) if apt_heat_durations else 0.0,
        "main_heat_hours": main_heat_seconds / 3600.0,
        "apartment_heat_hours": apt_heat_seconds / 3600.0,
        "main_heat_mode_hours": heat_mode_seconds / 3600.0,
        "auxiliary_heat_enable_hours": auxiliary_heat_enable_seconds / 3600.0,
        "main_calls": main_calls,
        "apartment_calls": apt_calls,
        "main_median_call_minutes": median(main_durations) if main_durations else 0.0,
        "apartment_median_call_minutes": median(apt_durations) if apt_durations else 0.0,
        "mean_oat_f": mean(oats) if oats else None,
        "max_oat_f": max(oats) if oats else None,
        "mean_active_supply_f": mean(active_supply) if active_supply else None,
        "fan_mean_absolute_error": mean(fan_errors) if fan_errors else None,
        "static_pressure_ok_percent": (
            sum(bool(row.get("STATIC_PRESSURE")) for row in rows) / len(rows) if rows else 0.0
        ),
        "ms1_fault_samples": sum(bool(row.get("ms1_fault_active")) for row in ms1_rows),
        "ms1_offline_samples": sum(row.get("ms1_state") == "OFFLINE" for row in ms1_rows),
        "ms1_ready_percent": (
            sum(row.get("ms1_state") == "READY" for row in ms1_rows) / len(ms1_rows)
            if ms1_rows else None
        ),
    }
    daily_rows = [
        {"date": day, "observed_hours": data["observed"] / 3600.0,
         "cooling_hours": data["cooling"] / 3600.0, "vent_hours": data["vent"] / 3600.0,
         "main_heat_hours": data["main_heat"] / 3600.0,
         "apartment_heat_hours": data["apt_heat"] / 3600.0}
        for day, data in sorted(day_seconds.items())
    ]
    hours = lambda data: {key: value / 3600.0 for key, value in sorted(data.items())}
    return Metrics(values, hours(state_seconds), hours(main_seconds), hours(apt_seconds), hours(fan_seconds), daily_rows)
