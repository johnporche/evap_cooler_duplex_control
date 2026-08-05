#!/usr/bin/env python3

import revpimodio2
import time
import csv
import json
import math
import os
import re
import signal
from datetime import datetime
from zoneinfo import ZoneInfo
from hvac_log_manager import RotatingCsvLog, RotatingTextLog
from hvac_prewet import select_prewet

try:
    from astral import LocationInfo
    from astral.sun import sun
    ASTRAL_AVAILABLE = True
except ImportError:
    ASTRAL_AVAILABLE = False


# ============================================================
# USER CONFIGURATION
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.environ.get("HVAC_LOG_DIR", "/home/pi")

STATE_LOG_DIR = os.path.join(LOG_DIR, "state")
EVENT_LOG_DIR = os.path.join(LOG_DIR, "events")
LOG_MAX_BYTES = int(os.environ.get("HVAC_LOG_MAX_BYTES", 50 * 1024 * 1024))
EVENT_LOG_MAX_BYTES = int(os.environ.get("HVAC_EVENT_LOG_MAX_BYTES", 25 * 1024 * 1024))

state_log = RotatingCsvLog(
    os.path.join(STATE_LOG_DIR, "current.csv"),
    maximum_bytes=LOG_MAX_BYTES,
)
event_log = RotatingTextLog(
    os.path.join(EVENT_LOG_DIR, "current.log"),
    maximum_bytes=EVENT_LOG_MAX_BYTES,
)

CALIBRATION_FILE = os.path.join(SCRIPT_DIR, "oat_calibration.csv")
THERM_REGRESSION_FILE = os.path.join(SCRIPT_DIR, "therm_regressions.json")
THERM_APT_FIT_FILE = os.path.join(SCRIPT_DIR, "therm_apt_fit.txt")
THERM_1ST_FIT_FILE = os.path.join(SCRIPT_DIR, "therm_1stflr_fit.txt")

FACTORY_TEMP_MIN_C = -50.0
FACTORY_TEMP_MAX_C = 50.0
FACTORY_RAW_MIN = 0.0
FACTORY_RAW_MAX = 10000.0

FAN_SPEED_COMMAND_VOLTS_INC = {
    0: 0.0,
    1: 2.8,
    2: 3.6,
    3: 4.4,
    4: 5.2,
    5: 6.0,
    6: 6.7,
    7: 7.5,
    8: 8.2,
    9: 9.0,
    10: 10.0,
}

FAN_SPEED_COMMAND_VOLTS_DEC = {
    0: 0.0,
    1: 2.2,
    2: 2.8,
    3: 3.6,
    4: 4.4,
    5: 5.2,
    6: 6.0,
    7: 6.8,
    8: 7.5,
    9: 8.3,
    10: 10.0,
}

FAN_SPEED_FEEDBACK_TYP_VOLTS = {
    0: 0.8,
    1: 1.3,
    2: 2.2,
    3: 3.2,
    4: 4.2,
    5: 5.2,
    6: 6.2,
    7: 7.2,
    8: 8.2,
    9: 9.3,
    10: 10.3,
}


CSV_INTERVAL_SECONDS = 5.0
LOOP_INTERVAL_SECONDS = 0.1
CONSOLE_HEARTBEAT_SECONDS = 5 * 60

MOUNTAIN_TZ = ZoneInfo("America/Denver")

LOCATION_NAME = "Denver"
LOCATION_REGION = "Colorado"
LOCATION_LATITUDE = 39.7392
LOCATION_LONGITUDE = -104.9903

# Analog output scale for RevPi MIO.
# If 10 V equals a raw value of 10000, leave this at 1000.
AO_SCALE = 1000

# Fan ramp settings.  Upward movement is deliberately slower for a gentle
# start.  Downward movement remains faster, but is still controlled.
# Limiting dt prevents a delayed loop iteration from creating a voltage jump.
FAN_RAMP_UP_VOLTS_PER_SECOND = 0.10
FAN_RAMP_DOWN_VOLTS_PER_SECOND = 0.20
FAN_RAMP_MAX_DT_SECONDS = 0.5

LOW_FAN_TARGET_SPEED = 1
MED_FAN_TARGET_SPEED = 5
HIGH_FAN_TARGET_SPEED = 10
NO_COOL_TARGET_SPEED = 0

# Combined fan target. Rows are Main Floor demand and columns are Apartment
# demand. Each thermostat is normalized to its highest active stage before
# this table is consulted (HIGH > MED > LOW > OFF).
FAN_TARGET_MAP = {
    "OFF":  {"OFF": 0, "LOW": 1, "MED": 5, "HIGH": 8},
    "LOW":  {"OFF": 1, "LOW": 2, "MED": 7, "HIGH": 10},
    "MED":  {"OFF": 5, "LOW": 7, "MED": 7, "HIGH": 10},
    "HIGH": {"OFF": 8, "LOW": 10, "MED": 10, "HIGH": 10},
}

# Fan-only (VENT) operation.  Ecobee commonly keeps its G/fan output active
# for a few minutes after ending a cooling call.  During that period the
# blower may run, but the evaporative-cooler pump must remain off.
VENT_MAX_TARGET_SPEED = 2
MAX_VENT_SECONDS = 15 * 60

# Warm weather shutdown hysteresis.
# WWSD turns on at 70 F and stays on until OAT drops to 65 F.
WWSD_ON_TEMP_F = 70.0
WWSD_OFF_TEMP_F = 65.0

# Per-floor mode logic.
# A floor can enter HEAT mode only at/below 50 F and last call was heat.
# A floor can enter COOL mode only above 70 F and last call was cool.
HEAT_MODE_OAT_F = 65.0
COOL_MODE_OAT_F = 60.0

# Damper protection.
# Damper progress is earned when STATIC_PRESSURE is True.
# Damper progress is lost when STATIC_PRESSURE is False.
DAMPER_REQUIRED_CLOSE_SECONDS = 60.0
DAMPER_STATIC_OK_SECONDS = 5.0
DAMPER_REVERSE_PENALTY_FACTOR = 1.0
DAMPER_MAX_SETTLE_SECONDS = 240.0

# Adaptive prewet logic.
PREWET_MIN_SECONDS = 5.0
PREWET_SHORT_SECONDS = 15.0
PREWET_NORMAL_SECONDS = 60.0
PREWET_LONG_SECONDS = 90.0

PAD_MIN_PREWET_WINDOW_SECONDS = 5 * 60
PAD_SHORT_PREWET_WINDOW_SECONDS = 30 * 60
PAD_DRY_TIME_SECONDS = 60 * 60
PREWET_HOT_OAT_F = 85.0


# ============================================================
# REVPI INITIALIZATION
# ============================================================

rpi = revpimodio2.RevPiModIO(autorefresh=True)

inputs = {
    "FRST_HEAT": rpi.io.T_DI01_FRST_HEAT,
    "FRST_COOL": rpi.io.T_DI02_FRST_COOL,
    "FRST_LOW": rpi.io.T_DI03_FRST_LOW,
    "FRST_MED": rpi.io.T_DI04_FRST_MED,
    "FRST_HIGH": rpi.io.T_DI05_FRST_HIGH,

    "APT_HEAT": rpi.io.T_DIO06_APT_HEAT,
    "APT_COOL": rpi.io.T_DI07_APT_COOL,
    "APT_LOW": rpi.io.T_DI08_APT_LOW,
    "APT_MED": rpi.io.T_DI09_APT_MED,
    "APT_HIGH": rpi.io.T_DI10_APT_HIGH,

    "STATIC_PRESSURE": rpi.io.T_DI11_STATIC_PRESSURE_STAT,
}

analog_inputs = {
    "FAN_SPEED": rpi.io.T_AI01_FAN_SPEED,
    "THERM_OUTDOOR": rpi.io.T_AI02_THERM_OUTDOOR,
    "ERROR_IN": rpi.io.T_AI03_ERROR_IN,
    "THERM_SUPPLY":rpi.io.T_AI04_THERM_SUPPLY,
    "THERM_1ST": rpi.io.T_AI05_THERM_1STFLR,
    "THERM_APT": rpi.io.T_AI06_THERM_APT
}

outputs = {
    "FRST_DMP_CLOSE": rpi.io.T_R1_FRST_DMP_CLOSE,
    "APT_DMP_CLOSE": rpi.io.T_R2_APT_DMP_CLOSE,
    "FRST_BOILER": rpi.io.T_R3_FRST_BOILER,
    "APT_BOILER": rpi.io.T_R4_APT_BOILER,

    "ANALOG_FAN_SPEED_DRV": rpi.io.T_AO6_ANALOG_FAN_SPEED_DRV,
    "BMS_PUMP_ON": rpi.io.T_AO7_BMS_PUMP_ON,
    "BMS_SYS_ON": rpi.io.T_AO8_BMS_SYS_ON,
    "WWSD": rpi.io.T_RevPiLED_WWSD,
}


# ============================================================
# PROGRAM STATE
# ============================================================

fan_current_volts = 0.0

warm_weather_shutdown = False

floor_modes = {
    "FRST": "IDLE",
    "APT": "IDLE",
}

last_calls = {
    "FRST": None,
    "APT": None,
}

calibration_points = []
calibration_mtime = None
supply_regressions = {}
supply_regression_signature = None

sun_cache_date = None
sun_cache = None

bms_state = "OFF"
bms_state_start_time = 0.0
static_ok_start_time = None
damper_close_progress_seconds = 0.0

last_pump_on_time = None
last_cooling_end_time = None
current_prewet_seconds = 0.0
current_prewet_reason = ""
vent_state_start_time = None
vent_timed_out = False
shutdown_requested = False

if ASTRAL_AVAILABLE:
    location = LocationInfo(
        name=LOCATION_NAME,
        region=LOCATION_REGION,
        timezone="America/Denver",
        latitude=LOCATION_LATITUDE,
        longitude=LOCATION_LONGITUDE,
    )
else:
    location = None


# ============================================================
# TIME AND LOGGING
# ============================================================

def mountain_now():
    return datetime.now(MOUNTAIN_TZ)


def timestamp_local():
    return mountain_now().strftime("%Y-%m-%d %H:%M:%S %Z")


def console_event(message):
    line = timestamp_local() + " | " + message
    print(line)
    event_log.append(line, mountain_now())


def request_shutdown(signum, frame):
    # Keep signal handling minimal.  The main loop observes this flag and then
    # exits through the existing `finally` block that places outputs in their
    # safe state.
    global shutdown_requested
    shutdown_requested = True


signal.signal(signal.SIGTERM, request_shutdown)


# ============================================================
# BASIC HELPERS
# ============================================================

def b(name):
    return bool(inputs[name].value)


def get_floor_request(prefix):
    """Return one internally consistent snapshot of a floor's thermostat inputs."""
    heat = b(prefix + "_HEAT")
    cool = b(prefix + "_COOL")
    low = b(prefix + "_LOW")
    med = b(prefix + "_MED")
    high = b(prefix + "_HIGH")
    fan = low or med or high

    if heat:
        mode = "HEAT"
    elif cool:
        mode = "COOL"
    elif fan:
        mode = "VENT"
    else:
        mode = "OFF"

    return {
        "mode": mode,
        "heat": heat,
        "cool": cool,
        "fan": fan,
        "low": low,
        "med": med,
        "high": high,
    }


def demand_level(request, air_allowed):
    if not air_allowed:
        return "OFF"
    if request["high"]:
        return "HIGH"
    if request["med"]:
        return "MED"
    if request["low"]:
        return "LOW"
    return "OFF"


def clamp(value, low, high):
    return max(low, min(high, value))


def ao_volts_to_raw(volts):
    volts = clamp(volts, 0.0, 10.0)
    return int(round(volts * AO_SCALE))

def raw_to_volts(raw_value):
    return float(raw_value) / 1000.0


def fan_feedback_speed_from_volts(volts):
    best_speed = 0
    best_error = 999.0

    for speed, typ_volts in FAN_SPEED_FEEDBACK_TYP_VOLTS.items():
        err = abs(volts - typ_volts)
        if err < best_error:
            best_error = err
            best_speed = speed

    return best_speed, best_error


def fan_command_volts_for_speed(target_speed, actual_speed):
    target_speed = int(clamp(target_speed, 0, 10))

    if target_speed > actual_speed:
        return FAN_SPEED_COMMAND_VOLTS_INC[target_speed]
    elif target_speed < actual_speed:
        return FAN_SPEED_COMMAND_VOLTS_DEC[target_speed]
    else:
        return FAN_SPEED_COMMAND_VOLTS_INC[target_speed]

def x_if_true(value):
    return "X" if bool(value) else "-"


def p_if_true(value):
    return "P" if bool(value) else "-"


def w_if_true(value):
    return "W" if bool(value) else "-"


def damper_symbol(is_closed):
    return "_" if bool(is_closed) else "|"


def level_symbol(level):
    level = int(clamp(level, 0, 10))
    if level == 10:
        return "X"
    return str(level)


def thermostat_call_symbol(heat_call, cool_call):
    if heat_call:
        return "H"
    if cool_call:
        return "C"
    return "-"


def fan_call_combined(low_call, med_call, high_call):
    if high_call:
        return "H"
    if med_call:
        return "M"
    if low_call:
        return "L"
    return "-"


def bms_output_on(raw_value):
    return int(raw_value) > 0

def sunrise_flag(now):
    s = update_sun_cache(now)

    if s is None:
        return "-"

    sunrise = s["sunrise"]

    if abs((now - sunrise).total_seconds()) <= 60:
        return "S"

    return "-"

def console_status_line(
    oat_f,
    oat_raw,
    therm_supply_f,
    frst_supply_f,
    apt_supply_f,
    frst_dmp_close,
    apt_dmp_close,
    need_damper_settle,
    fan_current_volts,
    fan_target_speed,
    fan_feedback_volts,
    fan_actual_speed
):
    now = mountain_now()

    oat_volts = raw_to_volts(oat_raw)
    frst_supply_delta_f = frst_supply_f - therm_supply_f
    apt_supply_delta_f = apt_supply_f - therm_supply_f

    frst_call = thermostat_call_symbol(
        b("FRST_HEAT"),
        b("FRST_COOL")
    )

    apt_call = thermostat_call_symbol(
        b("APT_HEAT"),
        b("APT_COOL")
    )

    frst_fan = fan_call_combined(
        b("FRST_LOW"),
        b("FRST_MED"),
        b("FRST_HIGH")
    )

    apt_fan = fan_call_combined(
        b("APT_LOW"),
        b("APT_MED"),
        b("APT_HIGH")
    )

    prewet_active = (
        bms_state == "PREPARE"
        and current_prewet_seconds > 0
    )

    waiting_damper = (
        need_damper_settle
        and bms_state == "PREPARE"
    )

    bms_sys_on = outputs["BMS_SYS_ON"].value > 0
    bms_pump_on = outputs["BMS_PUMP_ON"].value > 0

    bms_error = (
        "-" if bool(analog_inputs["ERROR_IN"].value)
        else "X"
    )

    static_symbol = (
        "-" if b("STATIC_PRESSURE")
        else "X"
    )

    return (
        f"{sunrise_flag(now)} "
        f"{oat_f:5.1f}F/{oat_volts:6.3f}V "

        f"{frst_call} "
        f"{x_if_true(b('FRST_LOW'))} "
        f"{x_if_true(b('FRST_MED'))} "
        f"{x_if_true(b('FRST_HIGH'))} "
        f"{frst_fan} "

        f"{apt_call} "
        f"{x_if_true(b('APT_LOW'))} "
        f"{x_if_true(b('APT_MED'))} "
        f"{x_if_true(b('APT_HIGH'))} "
        f"{apt_fan} "

        f"{p_if_true(prewet_active)} "
        f"{w_if_true(waiting_damper)} "

        f"{x_if_true(bms_sys_on)} "
        f"{p_if_true(bms_pump_on)} "

        f"{fan_current_volts:4.2f} "
        f"{level_symbol(fan_target_speed)} "

        f"{bms_error} "

        f"{fan_feedback_volts:4.2f} "
        f"{level_symbol(fan_actual_speed)} "

        f"{therm_supply_f:5.1f} "

        f"{damper_symbol(frst_dmp_close)} "
        f"{frst_supply_delta_f:+5.1f} "

        f"{damper_symbol(apt_dmp_close)} "
        f"{apt_supply_delta_f:+5.1f} "

        f"{static_symbol}"
    )
def console_change_key(
    frst_dmp_close,
    apt_dmp_close,
    need_damper_settle,
    fan_target_speed,
    fan_actual_speed
):
    return (
        thermostat_call_symbol(
            b("FRST_HEAT"),
            b("FRST_COOL")
        ),

        b("FRST_LOW"),
        b("FRST_MED"),
        b("FRST_HIGH"),

        thermostat_call_symbol(
            b("APT_HEAT"),
            b("APT_COOL")
        ),

        b("APT_LOW"),
        b("APT_MED"),
        b("APT_HIGH"),

        bms_state,

        need_damper_settle,

        outputs["BMS_SYS_ON"].value > 0,
        outputs["BMS_PUMP_ON"].value > 0,

        level_symbol(fan_target_speed),
        level_symbol(fan_actual_speed),

        damper_symbol(frst_dmp_close),
        damper_symbol(apt_dmp_close),
        b("STATIC_PRESSURE")
    )

# ============================================================
# SUNRISE AND SUNSET
# ============================================================

def update_sun_cache(now):
    global sun_cache_date
    global sun_cache

    if not ASTRAL_AVAILABLE:
        return None

    today = now.date()

    if sun_cache_date != today:
        s = sun(location.observer, date=today, tzinfo=MOUNTAIN_TZ)

        sun_cache = {
            "sunrise": s["sunrise"],
            "sunset": s["sunset"],
        }

        sun_cache_date = today

    return sun_cache


def sun_columns(now):
    s = update_sun_cache(now)

    if s is None:
        return {
            "sunrise_local": "",
            "sunset_local": "",
            "hours_since_sunrise": "",
            "hours_since_sunset": "",
            "hours_to_sunrise": "",
            "hours_to_sunset": "",
        }

    sunrise = s["sunrise"]
    sunset = s["sunset"]

    return {
        "sunrise_local": sunrise.isoformat(),
        "sunset_local": sunset.isoformat(),
        "hours_since_sunrise": round((now - sunrise).total_seconds() / 3600.0, 3),
        "hours_since_sunset": round((now - sunset).total_seconds() / 3600.0, 3),
        "hours_to_sunrise": round((sunrise - now).total_seconds() / 3600.0, 3),
        "hours_to_sunset": round((sunset - now).total_seconds() / 3600.0, 3),
    }



def factory_supply_temp_f_from_raw(raw_value):
    raw = float(raw_value)
    raw = clamp(raw, 0.0, 10000.0)

    return 40.0 + (raw / 10000.0) * (90.0 - 40.0)


def _regression_timestamp(value, fallback):
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp()
        except (TypeError, ValueError):
            pass
    return fallback


def _validated_regression(model, source, source_mtime):
    slope = float(model["slope"])
    intercept = float(model["intercept"])
    r2 = float(model["r2"]) if model.get("r2") is not None else None
    points = int(model["points"]) if model.get("points") is not None else None

    if not math.isfinite(slope) or not math.isfinite(intercept):
        raise ValueError("non-finite regression coefficient")
    if slope >= 0.0:
        raise ValueError("expected a negative thermistor regression slope")
    if r2 is not None and not 0.0 <= r2 <= 1.0:
        raise ValueError("R2 must be between 0 and 1")
    if points is not None and points < 2:
        raise ValueError("regression requires at least two points")

    return {
        "slope": slope,
        "intercept": intercept,
        "r2": r2,
        "points": points,
        "updated": model.get("updated", ""),
        "sort_time": _regression_timestamp(model.get("updated"), source_mtime),
        "source": source,
    }


def _load_regression_json(filename):
    with open(filename, "r") as f:
        data = json.load(f)

    source_mtime = os.path.getmtime(filename)
    candidates = {}
    for zone in ("1ST", "APT"):
        if zone in data:
            candidates[zone] = _validated_regression(
                data[zone],
                filename,
                source_mtime,
            )
    return candidates


def _load_regression_text(filename, zone):
    with open(filename, "r") as f:
        text = f.read()

    equation = re.search(
        r"temp_f\s*=\s*\(?\s*([-+]?\d+(?:\.\d+)?)\s*\*\s*volts\s*\)?"
        r"\s*\+\s*\(?\s*([-+]?\d+(?:\.\d+)?)",
        text,
    )
    if equation is None:
        raise ValueError("temperature regression equation not found")

    def optional(pattern, converter):
        match = re.search(pattern, text, re.IGNORECASE)
        return converter(match.group(1)) if match else None

    model = {
        "slope": float(equation.group(1)),
        "intercept": float(equation.group(2)),
        "points": optional(r"points\s*=\s*(\d+)", int),
        "r2": optional(r"R2\s*=\s*([-+]?\d+(?:\.\d+)?)", float),
        "updated": optional(
            r"updated\s*=\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})",
            str,
        ) or "",
    }
    return {
        zone: _validated_regression(
            model,
            filename,
            os.path.getmtime(filename),
        )
    }


def _supply_regression_file_signature():
    signature = []
    for filename in (
        THERM_REGRESSION_FILE,
        THERM_APT_FIT_FILE,
        THERM_1ST_FIT_FILE,
    ):
        try:
            stat = os.stat(filename)
            signature.append((filename, stat.st_mtime_ns, stat.st_size))
        except FileNotFoundError:
            signature.append((filename, None, None))
    return tuple(signature)


def get_supply_regressions():
    global supply_regressions
    global supply_regression_signature

    signature = _supply_regression_file_signature()
    if signature == supply_regression_signature:
        return supply_regressions

    candidates = {"1ST": [], "APT": []}
    errors = []
    loaders = (
        (THERM_REGRESSION_FILE, _load_regression_json, ()),
        (THERM_APT_FIT_FILE, _load_regression_text, ("APT",)),
        (THERM_1ST_FIT_FILE, _load_regression_text, ("1ST",)),
    )

    for filename, loader, args in loaders:
        if not os.path.exists(filename):
            continue
        try:
            loaded = loader(filename, *args)
            for zone, model in loaded.items():
                candidates[zone].append(model)
        except Exception as e:
            errors.append(os.path.basename(filename) + ": " + str(e))

    selected = {}
    for zone, models in candidates.items():
        if models:
            # Prefer the model with the newest embedded `updated` timestamp.
            # On a tie, prefer JSON because it retains full coefficient precision.
            selected[zone] = max(
                models,
                key=lambda model: (
                    model["sort_time"],
                    model["source"] == THERM_REGRESSION_FILE,
                ),
            )

    if selected:
        supply_regressions = selected
        supply_regression_signature = signature
        summary = []
        for zone in ("1ST", "APT"):
            if zone in selected:
                model = selected[zone]
                summary.append(
                    zone
                    + "="
                    + os.path.basename(model["source"])
                    + " R2="
                    + (format(model["r2"], ".5f") if model["r2"] is not None else "n/a")
                )
        console_event("Reloaded supply temperature regressions: " + ", ".join(summary))
    elif not supply_regressions:
        supply_regression_signature = signature
        console_event("No valid supply regressions; using factory formula")
    else:
        supply_regression_signature = signature
        console_event("No valid updated supply regressions; retaining prior values")

    if errors:
        console_event("Supply regression load warning: " + "; ".join(errors))

    return supply_regressions


def supply_temp_f_from_raw(raw_value, zone=None):
    raw = float(raw_value)
    volts = raw_to_volts(raw)

    if zone is not None:
        model = get_supply_regressions().get(zone)
        if model is not None:
            return model["slope"] * volts + model["intercept"]

    return factory_supply_temp_f_from_raw(raw)



# ============================================================
# OUTDOOR SENSOR CALIBRATION
#
# Calibration file:
#
# revpi_raw,boiler_temp_f
# 8305,72
# 7900,68
# 7500,64
#
# The file is reloaded automatically when it changes.
# ============================================================

def factory_oat_temp_f(raw_value):
    raw = float(raw_value)

    raw = clamp(raw, FACTORY_RAW_MIN, FACTORY_RAW_MAX)

    temp_c = (
        FACTORY_TEMP_MIN_C
        + (raw - FACTORY_RAW_MIN)
        * (FACTORY_TEMP_MAX_C - FACTORY_TEMP_MIN_C)
        / (FACTORY_RAW_MAX - FACTORY_RAW_MIN)
    )

    temp_f = temp_c * 9.0 / 5.0 + 32.0
    return temp_f



def load_calibration_table(filename):
    points = []

    with open(filename, "r") as f:
        reader = csv.DictReader(f)

        for row in reader:
            raw = float(row["revpi_raw"])
            temp_f = float(row["boiler_temp_f"])
            points.append((raw, temp_f))

    points.sort(key=lambda x: x[0])
    return points


def get_calibration_table():
    global calibration_points
    global calibration_mtime

    try:
        current_mtime = os.path.getmtime(CALIBRATION_FILE)

        if calibration_mtime != current_mtime:
            calibration_points = load_calibration_table(CALIBRATION_FILE)
            calibration_mtime = current_mtime

            console_event(
                "Reloaded OAT calibration table: "
                + str(len(calibration_points))
                + " points"
            )

    except FileNotFoundError:
        if calibration_mtime is not None:
            console_event("OAT calibration file not found: " + CALIBRATION_FILE)

        calibration_points = []
        calibration_mtime = None

    except Exception as e:
        console_event("Error loading OAT calibration table: " + str(e))

    return calibration_points


def interpolate_calibrated_temp(raw_value, points):
    raw_value = float(raw_value)

    if not points:
        return None

    if raw_value <= points[0][0]:
        return points[0][1]

    if raw_value >= points[-1][0]:
        return points[-1][1]

    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]

        if x0 <= raw_value <= x1:
            ratio = (raw_value - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)

    return None

def get_oat_calibrated_f():
    oat_raw = analog_inputs["THERM_OUTDOOR"].value
    points = get_calibration_table()

    if points:
        oat_calibrated_f = interpolate_calibrated_temp(oat_raw, points)
        oat_source = "calibration_table"
    else:
        oat_calibrated_f = factory_oat_temp_f(oat_raw)
        oat_source = "factory_formula"

    return oat_raw, oat_calibrated_f, points, oat_source



# ============================================================
# WARM WEATHER SHUTDOWN
# ============================================================

def update_wwsd(oat_calibrated_f):
    global warm_weather_shutdown

    if oat_calibrated_f is None:
        outputs["WWSD"].value = 0
        return warm_weather_shutdown

    old = warm_weather_shutdown

    if (not warm_weather_shutdown) and oat_calibrated_f >= WWSD_ON_TEMP_F:
        warm_weather_shutdown = True

    elif warm_weather_shutdown and oat_calibrated_f <= WWSD_OFF_TEMP_F:
        warm_weather_shutdown = False

    outputs["WWSD"].value = 1 if warm_weather_shutdown else 0

    if warm_weather_shutdown != old:
        if warm_weather_shutdown:
            console_event("WWSD ON: OAT=" + format(oat_calibrated_f, ".1f") + " F")
        else:
            console_event("WWSD OFF: OAT=" + format(oat_calibrated_f, ".1f") + " F")

    return warm_weather_shutdown


# ============================================================
# FLOOR MODES
# ============================================================

def update_floor_modes(oat_calibrated_f):
    global floor_modes
    global last_calls

    if b("FRST_HEAT"):
        last_calls["FRST"] = "HEAT"
    elif b("FRST_COOL"):
        last_calls["FRST"] = "COOL"

    if b("APT_HEAT"):
        last_calls["APT"] = "HEAT"
    elif b("APT_COOL"):
        last_calls["APT"] = "COOL"

    if oat_calibrated_f is None:
        print("oat_calibrated is none")
        return floor_modes

    old_modes = floor_modes.copy()

    if oat_calibrated_f <= HEAT_MODE_OAT_F and last_calls["FRST"] == "HEAT":
        floor_modes["FRST"] = "HEAT"

    elif oat_calibrated_f > COOL_MODE_OAT_F and last_calls["FRST"] == "COOL":
        floor_modes["FRST"] = "COOL"


    if oat_calibrated_f <= HEAT_MODE_OAT_F and last_calls["APT"] == "HEAT":
        floor_modes["APT"] = "HEAT"

    elif oat_calibrated_f > COOL_MODE_OAT_F and last_calls["APT"] == "COOL":
        floor_modes["APT"] = "COOL"


    if floor_modes != old_modes:
        console_event(
            "Mode change | "
            + "1st=" + floor_modes["FRST"]
            + " last=" + str(last_calls["FRST"])
            + " | apt=" + floor_modes["APT"]
            + " last=" + str(last_calls["APT"])
            + " | OAT=" + format(oat_calibrated_f, ".1f") + " F"
        )

    return floor_modes


# ============================================================
# DAMPER CONTROL
# ============================================================
def dampers_need_settle(frst_dmp_close, apt_dmp_close, airflow_requested):
    if not airflow_requested:
        return False

    # If both dampers are open, airflow path is safe.
    if not frst_dmp_close and not apt_dmp_close:
        return False

    # If fan is already running, do not interrupt just because damper command changed.
    if bms_state in ("RUN", "VENT"):
        return False

    # Otherwise, at least one damper is being commanded closed before startup.
    return True


def apply_airflow_damper_logic(floor_requests):
    frst_request = floor_requests["FRST"]
    apt_request = floor_requests["APT"]

    frst_cool_allowed = frst_request["cool"] and floor_modes["FRST"] == "COOL"
    apt_cool_allowed = apt_request["cool"] and floor_modes["APT"] == "COOL"

    # A fan request without heat or cool is the Ecobee's ventilation/fan-only
    # request.  Only honor it while that floor is in cooling season mode so a
    # heating fan overrun cannot accidentally start the evaporative cooler.
    frst_vent_allowed = (
        frst_request["mode"] == "VENT"
        and floor_modes["FRST"] == "COOL"
    )
    apt_vent_allowed = (
        apt_request["mode"] == "VENT"
        and floor_modes["APT"] == "COOL"
    )

    frst_air_allowed = frst_cool_allowed or frst_vent_allowed
    apt_air_allowed = apt_cool_allowed or apt_vent_allowed

    frst_close = False
    apt_close = False

    if frst_air_allowed and not apt_air_allowed:
        frst_close = False
        apt_close = True

    elif apt_air_allowed and not frst_air_allowed:
        frst_close = True
        apt_close = False

    elif frst_air_allowed and apt_air_allowed:
        frst_close = False
        apt_close = False

    else:
        frst_close = False
        apt_close = False

    if frst_close and apt_close:
        frst_close = False
        apt_close = False
        console_event("SAFETY: both dampers would close, forced both open")

    outputs["FRST_DMP_CLOSE"].value = frst_close
    outputs["APT_DMP_CLOSE"].value = apt_close

    return (
        frst_close,
        apt_close,
        frst_cool_allowed,
        apt_cool_allowed,
        frst_vent_allowed,
        apt_vent_allowed,
        frst_air_allowed,
        apt_air_allowed,
    )


# ============================================================
# FAN TARGET AND RAMP
# ============================================================
def ramp_fan_voltage(current, target, dt):
    safe_dt = clamp(dt, 0.0, FAN_RAMP_MAX_DT_SECONDS)

    if current < target:
        max_change = FAN_RAMP_UP_VOLTS_PER_SECOND * safe_dt
        return min(current + max_change, target)

    if current > target:
        max_change = FAN_RAMP_DOWN_VOLTS_PER_SECOND * safe_dt
        return max(current - max_change, target)

    return current


# ============================================================
# HEATING OUTPUTS
# ============================================================

def apply_heating_logic():
    frst_heat_allowed = (
        b("FRST_HEAT")
        and floor_modes["FRST"] == "HEAT"
        and not warm_weather_shutdown
    )

    apt_heat_allowed = (
        b("APT_HEAT")
        and floor_modes["APT"] == "HEAT"
        and not warm_weather_shutdown  
    )

    outputs["FRST_BOILER"].value = frst_heat_allowed
    outputs["APT_BOILER"].value = apt_heat_allowed

    return frst_heat_allowed, apt_heat_allowed


# ============================================================
# ADAPTIVE PREWET LOGIC
# ============================================================

def determine_prewet_seconds(now_mono, oat_f):
    seconds_since_pump = None
    if last_pump_on_time is not None:
        seconds_since_pump = now_mono - last_pump_on_time

    return select_prewet(
        seconds_since_pump=seconds_since_pump,
        oat_f=oat_f,
        minimum_seconds=PREWET_MIN_SECONDS,
        short_seconds=PREWET_SHORT_SECONDS,
        normal_seconds=PREWET_NORMAL_SECONDS,
        long_seconds=PREWET_LONG_SECONDS,
        minimum_window_seconds=PAD_MIN_PREWET_WINDOW_SECONDS,
        short_window_seconds=PAD_SHORT_PREWET_WINDOW_SECONDS,
        dry_time_seconds=PAD_DRY_TIME_SECONDS,
        hot_oat_f=PREWET_HOT_OAT_F,
    )


# ============================================================
# BMS SEQUENCE
#
# OFF
#   No cooling requested.
#
# PREPARE
#   Dampers are commanded first.
#   System and pump are on for prewet; fan is held off.
#   Damper progress is earned while STATIC_PRESSURE is True.
#   Damper progress is lost while STATIC_PRESSURE is False.
#
# PREWET
#   BMS system on.
#   Pump on.
#   Fan held at 0 V.
#
# RUN
#   Pump on.
#   System on.
#   Fan allowed to ramp toward Ecobee requested speed.
#
# VENT_PREPARE
#   System on and pump off.
#   Fan held off while a newly selected zone damper settles.
#
# VENT
#   System on and pump off.
#   Fan follows the Ecobee request, capped at VENT_MAX_TARGET_SPEED.
# ============================================================
def update_bms_sequence(
    cooling_requested,
    vent_requested,
    need_damper_settle,
    now_mono,
    dt,
    oat_f,
):
    global bms_state
    global bms_state_start_time
    global static_ok_start_time
    global damper_close_progress_seconds
    global last_pump_on_time
    global last_cooling_end_time
    global current_prewet_seconds
    global current_prewet_reason
    global vent_state_start_time
    global vent_timed_out

    fan_allowed = False
    static_ok = b("STATIC_PRESSURE")

    # Cooling always takes priority over ventilation.  The timeout latch is
    # reset once the Ecobee removes its fan-only request.
    vent_only_requested = vent_requested and not cooling_requested

    if cooling_requested or not vent_requested:
        vent_state_start_time = None
        vent_timed_out = False
    elif vent_state_start_time is None:
        vent_state_start_time = now_mono

    if (
        vent_only_requested
        and vent_state_start_time is not None
        and now_mono - vent_state_start_time >= MAX_VENT_SECONDS
    ):
        if not vent_timed_out:
            console_event("BMS VENT timeout: fan-only request exceeded limit")
        vent_timed_out = True

    if vent_timed_out:
        vent_only_requested = False

    if not cooling_requested and not vent_only_requested:
        if bms_state != "OFF":
            console_event("BMS OFF: all airflow requests ended")
            if outputs["BMS_PUMP_ON"].value > 0:
                last_cooling_end_time = now_mono

        bms_state = "OFF"
        bms_state_start_time = now_mono
        static_ok_start_time = None
        damper_close_progress_seconds = 0.0
        current_prewet_seconds = 0.0
        current_prewet_reason = ""

        outputs["BMS_SYS_ON"].value = 0
        outputs["BMS_PUMP_ON"].value = 0

        return bms_state, fan_allowed

    if vent_only_requested:
        if bms_state in ("RUN", "PREPARE"):
            if outputs["BMS_PUMP_ON"].value > 0:
                last_cooling_end_time = now_mono

            # A normal post-cool transition keeps the fan running.  If the
            # zone allocation changed at the same instant, pause for damper
            # preparation before resuming ventilation.
            bms_state = "VENT_PREPARE" if need_damper_settle else "VENT"
            bms_state_start_time = now_mono
            static_ok_start_time = None
            damper_close_progress_seconds = 0.0
            console_event("BMS VENT: cooling ended, fan-only request remains")

        elif bms_state == "OFF":
            bms_state = "VENT_PREPARE"
            bms_state_start_time = now_mono
            static_ok_start_time = None
            damper_close_progress_seconds = 0.0
            console_event("BMS VENT PREPARE: fan-only request started")

        if bms_state == "VENT_PREPARE":
            outputs["BMS_SYS_ON"].value = 10000
            outputs["BMS_PUMP_ON"].value = 0
            fan_allowed = False

            if need_damper_settle:
                if static_ok:
                    damper_close_progress_seconds += dt
                    if static_ok_start_time is None:
                        static_ok_start_time = now_mono
                else:
                    damper_close_progress_seconds -= (
                        dt * DAMPER_REVERSE_PENALTY_FACTOR
                    )
                    static_ok_start_time = None

                damper_close_progress_seconds = clamp(
                    damper_close_progress_seconds,
                    0.0,
                    DAMPER_REQUIRED_CLOSE_SECONDS,
                )
                static_ok_elapsed = 0.0
                if static_ok_start_time is not None:
                    static_ok_elapsed = now_mono - static_ok_start_time

                damper_ready = (
                    damper_close_progress_seconds >= DAMPER_REQUIRED_CLOSE_SECONDS
                    and static_ok_elapsed >= DAMPER_STATIC_OK_SECONDS
                )
                damper_timeout = (
                    now_mono - bms_state_start_time >= DAMPER_MAX_SETTLE_SECONDS
                )
            else:
                damper_ready = True
                damper_timeout = False

            if damper_ready or damper_timeout:
                bms_state = "VENT"
                bms_state_start_time = now_mono
                console_event("BMS VENT RUN: damper preparation complete")

        elif bms_state == "VENT":
            outputs["BMS_SYS_ON"].value = 10000
            outputs["BMS_PUMP_ON"].value = 0
            fan_allowed = True

        return bms_state, fan_allowed

    if bms_state in ("OFF", "VENT", "VENT_PREPARE"):
        resumed_from_vent = bms_state in ("VENT", "VENT_PREPARE")
        bms_state = "PREPARE"
        bms_state_start_time = now_mono
        static_ok_start_time = None
        damper_close_progress_seconds = 0.0

        current_prewet_seconds, current_prewet_reason = (
            determine_prewet_seconds(now_mono, oat_f)
        )

        console_event(
            ("BMS COOL resumed from vent: prewet=" if resumed_from_vent
             else "BMS PREPARE started: prewet=")
            + format(current_prewet_seconds, ".0f")
            + " sec, damper_wait="
            + ("YES" if need_damper_settle else "no")
            + ", reason="
            + current_prewet_reason
        )

    elapsed = now_mono - bms_state_start_time

    if bms_state == "PREPARE":
        # Pump/system on for prewet while dampers are moving.
        # Fan remains off.
        outputs["BMS_SYS_ON"].value = 10000
        outputs["BMS_PUMP_ON"].value = 10000
        last_pump_on_time = now_mono
        fan_allowed = False

        if need_damper_settle:
            if static_ok:
                damper_close_progress_seconds += dt

                if static_ok_start_time is None:
                    static_ok_start_time = now_mono
            else:
                damper_close_progress_seconds -= dt * DAMPER_REVERSE_PENALTY_FACTOR
                static_ok_start_time = None

            damper_close_progress_seconds = clamp(
                damper_close_progress_seconds,
                0.0,
                DAMPER_REQUIRED_CLOSE_SECONDS
            )

            static_ok_elapsed = 0.0
            if static_ok_start_time is not None:
                static_ok_elapsed = now_mono - static_ok_start_time

            damper_ready = (
                damper_close_progress_seconds >= DAMPER_REQUIRED_CLOSE_SECONDS
                and static_ok_elapsed >= DAMPER_STATIC_OK_SECONDS
            )

            damper_timeout = elapsed >= DAMPER_MAX_SETTLE_SECONDS
        else:
            damper_ready = True
            damper_timeout = False
            damper_close_progress_seconds = DAMPER_REQUIRED_CLOSE_SECONDS

        prewet_ready = elapsed >= current_prewet_seconds

        if prewet_ready and (damper_ready or damper_timeout):
            bms_state = "RUN"
            bms_state_start_time = now_mono

            console_event(
                "BMS RUN: prewet and damper preparation complete"
            )

    elif bms_state == "RUN":
        outputs["BMS_SYS_ON"].value = 10000
        outputs["BMS_PUMP_ON"].value = 10000
        last_pump_on_time = now_mono
        fan_allowed = True

    else:
        bms_state = "OFF"
        bms_state_start_time = now_mono
        static_ok_start_time = None
        damper_close_progress_seconds = 0.0
        current_prewet_seconds = 0.0
        current_prewet_reason = ""

        outputs["BMS_SYS_ON"].value = 0
        outputs["BMS_PUMP_ON"].value = 0
        fan_allowed = False

    return bms_state, fan_allowed




# ============================================================
# CSV LOGGING
# ============================================================

def get_state_snapshot(extra):
    now = mountain_now()
    oat_raw, oat_calibrated_f, points, oat_source = get_oat_calibrated_f()

    row = {
        "timestamp_local": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "timestamp_iso": now.isoformat(),
    }

    row.update(sun_columns(now))

    row["oat_revpi_raw"] = oat_raw
    row["oat_revpi_volts"] = round(raw_to_volts(oat_raw), 4)
    row["oat_calibrated_boiler_f"] = (
        round(oat_calibrated_f, 2) if oat_calibrated_f is not None else ""
    )
    row["oat_calibration_points"] = len(points)
    row["oat_calibration_mtime"] = (
        calibration_mtime if calibration_mtime is not None else ""
    )
    row["oat_source"]=oat_source
    therm_supply_raw = analog_inputs["THERM_SUPPLY"].value
    therm_supply_f = supply_temp_f_from_raw(therm_supply_raw)

    row["therm_supply_raw"] = therm_supply_raw
    row["therm_supply_f"] = round(therm_supply_f, 2)

    supply_models = get_supply_regressions()
    for zone, input_name, field_prefix in (
        ("1ST", "THERM_1ST", "therm_1st"),
        ("APT", "THERM_APT", "therm_apt"),
    ):
        raw = analog_inputs[input_name].value
        model = supply_models.get(zone)
        temp_f = supply_temp_f_from_raw(raw, zone)
        row[field_prefix + "_raw"] = raw
        row[field_prefix + "_f"] = round(temp_f, 2)
        row[field_prefix + "_delta_from_supply_f"] = round(
            temp_f - therm_supply_f,
            2,
        )
        row[field_prefix + "_source"] = (
            os.path.basename(model["source"])
            if model is not None
            else "factory_formula"
        )
        row[field_prefix + "_slope"] = model["slope"] if model else ""
        row[field_prefix + "_intercept"] = model["intercept"] if model else ""
        row[field_prefix + "_r2"] = model["r2"] if model else ""
        row[field_prefix + "_points"] = model["points"] if model else ""
        row[field_prefix + "_updated"] = model["updated"] if model else ""
    row["warm_weather_shutdown"] = warm_weather_shutdown
    row["wwsd_on_temp_f"] = WWSD_ON_TEMP_F
    row["wwsd_off_temp_f"] = WWSD_OFF_TEMP_F

    row["frst_mode"] = floor_modes["FRST"]
    row["apt_mode"] = floor_modes["APT"]
    row["frst_last_call"] = last_calls["FRST"] if last_calls["FRST"] else ""
    row["apt_last_call"] = last_calls["APT"] if last_calls["APT"] else ""

    row["bms_state"] = bms_state
    row["damper_close_progress_seconds"] = round(
        damper_close_progress_seconds, 3
    )
    row["damper_required_close_seconds"] = DAMPER_REQUIRED_CLOSE_SECONDS
    row["damper_reverse_penalty_factor"] = DAMPER_REVERSE_PENALTY_FACTOR
    row["current_prewet_seconds"] = current_prewet_seconds
    row["current_prewet_reason"] = current_prewet_reason

    if last_pump_on_time is None:
        row["last_pump_on_age_seconds"] = ""
    else:
        row["last_pump_on_age_seconds"] = extra.get("last_pump_on_age_seconds","")

    for name, io in inputs.items():
        row[name] = bool(io.value)

    for name, io in analog_inputs.items():
        row[name] = io.value

    for name, io in outputs.items():
        row[name] = io.value

    row.update(extra)

    return row


def ensure_csv_header(fieldnames):
    state_log.ensure_header(fieldnames, mountain_now())


def append_csv(row, fieldnames):
    state_log.append(row, fieldnames, mountain_now())


# ============================================================
# MAIN LOOP
# ============================================================

try:
    console_event("HVAC controller started")

    if not ASTRAL_AVAILABLE:
        console_event("Astral not installed. Sunrise/sunset columns will be blank.")
        console_event("Install with: pip3 install astral")

    last_console_state = None
    last_console_time = None
    last_csv_time = 0.0
    last_loop_time = time.monotonic()

    first_row = get_state_snapshot({
        "fan_target_speed": 0,
        "fan_actual_speed": 0,
        "fan_feedback_raw": 0,
        "fan_feedback_volts": 0.0,
        "fan_feedback_error": 0.0,
        "fan_error_speed": 0,
        "fan_target_volts": 0.0,
        "fan_current_volts": 0.0,
        "fan_error_volts": 0.0,
        "fan_speed_request": "OFF",
        "fan_allowed": False,
        "need_damper_settle":False,
        "frst_cool_allowed": False,
        "apt_cool_allowed": False,
        "frst_vent_allowed": False,
        "apt_vent_allowed": False,
        "frst_air_allowed": False,
        "apt_air_allowed": False,
        "frst_heat_allowed": False,
        "apt_heat_allowed": False,
        "frst_request_mode": "OFF",
        "apt_request_mode": "OFF",
        "frst_demand_level": "OFF",
        "apt_demand_level": "OFF",
        "cooling_requested": False,
        "vent_requested": False,
        "vent_timed_out": False,
        "airflow_requested": False,
        "vent_active": False,
        "cooling_active": False,
        "last_pump_on_age_seconds": "",
        
    })

    csv_fieldnames = list(first_row.keys())
    ensure_csv_header(csv_fieldnames)

    while not shutdown_requested:
        now_mono = time.monotonic()
        dt = now_mono - last_loop_time
        last_loop_time = now_mono

        oat_raw, oat_calibrated_f, points, oat_source = get_oat_calibrated_f()
        therm_supply_raw = analog_inputs["THERM_SUPPLY"].value
        therm_supply_f = supply_temp_f_from_raw(therm_supply_raw)
        update_wwsd(oat_calibrated_f)
        update_floor_modes(oat_calibrated_f)

        floor_requests = {
            "FRST": get_floor_request("FRST"),
            "APT": get_floor_request("APT"),
        }

        frst_heat_allowed, apt_heat_allowed = apply_heating_logic()

        (
            frst_dmp_close,
            apt_dmp_close,
            frst_cool_allowed,
            apt_cool_allowed,
            frst_vent_allowed,
            apt_vent_allowed,
            frst_air_allowed,
            apt_air_allowed,
        ) = apply_airflow_damper_logic(floor_requests)

        cooling_requested = frst_cool_allowed or apt_cool_allowed
        vent_requested = frst_vent_allowed or apt_vent_allowed
        airflow_requested = cooling_requested or vent_requested

        need_damper_settle = dampers_need_settle(
                             frst_dmp_close,
                             apt_dmp_close,
                             airflow_requested
                             )

        bms_state_now, fan_allowed = update_bms_sequence(
                             cooling_requested,
                             vent_requested,
                             need_damper_settle,
                             now_mono,
                             dt,
                             oat_calibrated_f
                             )
        fan_feedback_raw = analog_inputs["FAN_SPEED"].value
        fan_feedback_volts = raw_to_volts(fan_feedback_raw)
        fan_actual_speed, fan_feedback_error = fan_feedback_speed_from_volts(
                                               fan_feedback_volts  )

        frst_demand_level = demand_level(
            floor_requests["FRST"],
            frst_air_allowed,
        )
        apt_demand_level = demand_level(
            floor_requests["APT"],
            apt_air_allowed,
        )

        if fan_allowed:
           fan_target_speed = FAN_TARGET_MAP[frst_demand_level][apt_demand_level]
           fan_request = str(fan_target_speed)
           if vent_requested and not cooling_requested:
               fan_target_speed = min(
                   fan_target_speed,
                   VENT_MAX_TARGET_SPEED,
               )
               fan_request = "VENT_" + str(fan_target_speed)
        else:
            fan_target_speed = 0
            fan_request = bms_state_now

        fan_target_volts = fan_command_volts_for_speed(
            fan_target_speed,
            fan_actual_speed
            )

        fan_current_volts = ramp_fan_voltage(
            fan_current_volts,
            fan_target_volts,
            dt
            )

        outputs["ANALOG_FAN_SPEED_DRV"].value = ao_volts_to_raw(
            fan_current_volts
            )

        fan_error_speed = fan_target_speed - fan_actual_speed


        cooling_active = cooling_requested and fan_allowed
        vent_active = vent_requested and not cooling_requested and fan_allowed
        fan_error_volts = fan_target_volts - fan_current_volts

        if last_pump_on_time is None:
            pump_age = ""
        else:
            pump_age = round(now_mono - last_pump_on_time, 1)

        frst_supply_f = supply_temp_f_from_raw(
            analog_inputs["THERM_1ST"].value,
            "1ST",
        )
        apt_supply_f = supply_temp_f_from_raw(
            analog_inputs["THERM_APT"].value,
            "APT",
        )

        console_state = console_change_key(
            frst_dmp_close,
            apt_dmp_close,
            need_damper_settle,
            fan_target_speed,
            fan_actual_speed
            )

        heartbeat_due = (
            last_console_time is None
            or now_mono - last_console_time >= CONSOLE_HEARTBEAT_SECONDS
        )

        if console_state != last_console_state or heartbeat_due:
            console_event(
                console_status_line(
                    oat_calibrated_f,
                    oat_raw,
                    therm_supply_f,
                    frst_supply_f,
                    apt_supply_f,
                    frst_dmp_close,
                    apt_dmp_close,
                    need_damper_settle,
                    fan_current_volts,
                    fan_target_speed,
                    fan_feedback_volts,
                    fan_actual_speed
                )
            )
            last_console_time = now_mono

        last_console_state = console_state

    
        if now_mono - last_csv_time >= CSV_INTERVAL_SECONDS:
            row = get_state_snapshot({
                "fan_target_speed": fan_target_speed,
                "fan_actual_speed": fan_actual_speed,
                "fan_feedback_raw": fan_feedback_raw,
                "fan_feedback_volts": round(fan_feedback_volts, 3),
                "fan_feedback_error": round(fan_feedback_error, 3),
                "fan_error_speed": fan_error_speed,
                "fan_target_volts": round(fan_target_volts, 3),
                "fan_current_volts": round(fan_current_volts, 3),
                "fan_error_volts": round(fan_error_volts, 3),
                "fan_speed_request": fan_request,
                "fan_allowed": fan_allowed,
                "need_damper_settle": need_damper_settle,
                "frst_cool_allowed": frst_cool_allowed,
                "apt_cool_allowed": apt_cool_allowed,
                "frst_vent_allowed": frst_vent_allowed,
                "apt_vent_allowed": apt_vent_allowed,
                "frst_air_allowed": frst_air_allowed,
                "apt_air_allowed": apt_air_allowed,
                "frst_heat_allowed": frst_heat_allowed,
                "apt_heat_allowed": apt_heat_allowed,
                "frst_request_mode": floor_requests["FRST"]["mode"],
                "apt_request_mode": floor_requests["APT"]["mode"],
                "frst_demand_level": frst_demand_level,
                "apt_demand_level": apt_demand_level,
                "cooling_requested": cooling_requested,
                "vent_requested": vent_requested,
                "vent_timed_out": vent_timed_out,
                "airflow_requested": airflow_requested,
                "vent_active": vent_active,
                "cooling_active": cooling_active,
                "last_pump_on_age_seconds": pump_age,
            })

            append_csv(row, csv_fieldnames)
            last_csv_time = now_mono

        time.sleep(LOOP_INTERVAL_SECONDS)

    console_event("Controller shutdown requested")

except KeyboardInterrupt:
    console_event("Controller interrupted by user")

finally:
    outputs["ANALOG_FAN_SPEED_DRV"].value = 0
    outputs["BMS_PUMP_ON"].value = 0
    outputs["BMS_SYS_ON"].value = 0

    outputs["FRST_DMP_CLOSE"].value = 0
    outputs["APT_DMP_CLOSE"].value = 0

    outputs["FRST_BOILER"].value = 0
    outputs["APT_BOILER"].value = 0

    outputs["WWSD"].value = 0

    console_event("Controller exiting. Fan off, BMS off, boilers off, dampers open.")
    #rpi.close()
