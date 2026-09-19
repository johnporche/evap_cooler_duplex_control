"""Pure two-zone airflow allocation helpers, independent of RevPi hardware."""


def next_post_cool_state(
    previous_cool,
    post_cool_active,
    heat,
    cool,
    fan,
    timed_out=False,
):
    """Return ``(current_cool_memory, post_cool_active)`` for one zone.

    Post-cool ventilation starts only on a COOL falling edge while a fan-stage
    input remains active. A later standalone fan call is therefore not
    mistaken for post-cool operation. Heat always cancels the state because
    the evaporative-cooler fan is unavailable for heating.
    """
    if heat:
        return False, False

    if cool:
        return True, False

    if timed_out:
        return False, False

    if previous_cool and fan:
        return False, True

    if post_cool_active and fan:
        return False, True

    return False, False


def next_post_heat_fan_suppression(
    previous_heat,
    suppressed,
    heat,
    cool,
    fan,
):
    """Return ``(current_heat_memory, suppress_fan)`` for one zone.

    A fan signal that remains asserted when HEAT ends is treated as heat-system
    overrun, not as a new ventilation request. Suppression remains latched
    until every fan stage drops. A cooling call also clears it because cooling
    owns the fan request at that point.
    """
    if heat:
        return True, False

    if cool or not fan:
        return False, False

    if previous_heat and fan:
        return False, True

    return False, bool(suppressed and fan)


def select_zone_airflow(
    frst_cool_allowed,
    apt_cool_allowed,
    frst_vent_allowed,
    apt_vent_allowed,
):
    """Return zone airflow permissions with active cooling taking priority.

    A post-cooling fan-only request keeps its zone open only while there is no
    wet-cooling call from either zone. If either zone requests wet cooling,
    airflow is allocated only to the zones that are actively cooling.
    """
    cooling_requested = frst_cool_allowed or apt_cool_allowed

    if cooling_requested:
        return bool(frst_cool_allowed), bool(apt_cool_allowed)

    return bool(frst_vent_allowed), bool(apt_vent_allowed)


def select_damper_commands(frst_air_allowed, apt_air_allowed):
    """Return ``(first_floor_close, apartment_close)`` fail-safe commands."""
    if frst_air_allowed and not apt_air_allowed:
        return False, True
    if apt_air_allowed and not frst_air_allowed:
        return True, False

    # Both zones requesting air, or neither zone requesting air, leaves both
    # dampers open. This also makes it impossible to command both closed.
    return False, False


def dampers_require_startup_settle(
    frst_dmp_close,
    apt_dmp_close,
    airflow_requested,
    bms_state,
):
    """Return whether startup must wait for a commanded damper closure."""
    if not airflow_requested:
        return False
    if not frst_dmp_close and not apt_dmp_close:
        return False

    # RUN is already protected by established airflow. VENT is deliberately
    # not exempt: a VENT-to-cooling transition may reverse zone allocation and
    # must settle the newly closing damper while the fan is held off.
    return bms_state != "RUN"
