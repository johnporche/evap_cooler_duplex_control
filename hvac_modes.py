"""Pure thermostat request and equipment-inhibition diagnostics."""


def ms1_inhibition_reason(state, fault_code=None):
    """Return a stable reason code for an unavailable MS1 state."""
    if state == "FAULT":
        if fault_code is None:
            return "MS1_FAULT_FC_UNKNOWN"
        return "MS1_FAULT_FC" + format(int(fault_code), "02d")
    if state == "OFFLINE":
        return "MS1_OFFLINE"
    if state == "UNKNOWN":
        return "MS1_STARTUP_UNKNOWN"
    return "MS1_" + str(state or "UNKNOWN")


def describe_zone_mode(
    *,
    heat,
    cool,
    fan,
    post_cool_active,
    warm_weather_shutdown,
    cooler_state,
    cooler_fault_code=None,
    low_oat_lockout=False,
    oat_known=True,
):
    """Return requested mode, effective mode, and a stable reason code."""
    if heat:
        requested = "HEAT"
        if warm_weather_shutdown:
            return requested, "HEAT_BLOCKED", "WWSD_ACTIVE"
        if cool:
            return requested, "HEAT", "INPUT_CONFLICT_HEAT_PRIORITY"
        return requested, "HEAT", "NONE"

    if cool:
        requested = "COOL"
        if cooler_state != "READY":
            return (
                requested,
                "COOL_BLOCKED",
                ms1_inhibition_reason(cooler_state, cooler_fault_code),
            )
        if low_oat_lockout:
            reason = (
                "LOW_OAT_PUMP_LOCKOUT"
                if oat_known
                else "OAT_UNKNOWN_PUMP_SAFE"
            )
            return requested, "FREE_COOL", reason
        return requested, "COOL", "NONE"

    if fan:
        requested = "VENT"
        if cooler_state != "READY":
            return (
                requested,
                "VENT_BLOCKED",
                ms1_inhibition_reason(cooler_state, cooler_fault_code),
            )
        return requested, "VENT", "NONE"

    return "OFF", "OFF", "NONE"
