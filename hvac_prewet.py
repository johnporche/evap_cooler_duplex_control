"""Pure adaptive-prewet selection logic, independent of RevPi hardware."""


def select_prewet(
    seconds_since_pump,
    oat_f,
    minimum_seconds=5.0,
    short_seconds=15.0,
    normal_seconds=60.0,
    long_seconds=90.0,
    minimum_window_seconds=5 * 60,
    short_window_seconds=30 * 60,
    dry_time_seconds=60 * 60,
    hot_oat_f=85.0,
):
    """Return ``(seconds, reason)`` for the next cooling startup."""
    if seconds_since_pump is None:
        return long_seconds, "first_start"

    age = max(0.0, float(seconds_since_pump))

    if age <= minimum_window_seconds:
        return minimum_seconds, "immediate_restart"

    if age <= short_window_seconds:
        if oat_f is not None and oat_f >= hot_oat_f:
            return normal_seconds, "recent_restart_hot"
        return short_seconds, "pads_recently_wet"

    if age >= dry_time_seconds:
        return long_seconds, "pads_likely_dry"

    return normal_seconds, "normal_restart"

