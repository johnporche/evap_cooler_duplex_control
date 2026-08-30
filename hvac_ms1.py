"""Decode the Seeley MS1 PWR / ERROR CODE voltage waveform.

The signal is high while the cooler interface is powered and healthy, low
while it is unpowered, and pulses low in groups when a cooler fault is active.
This module deliberately has no RevPi dependencies so its timing can be tested.
"""

from dataclasses import dataclass
from typing import Optional


FAULT_DESCRIPTIONS = {
    1: "communication failure",
    2: "failure to detect water at probes",
    4: "failure to clear probes during drain",
    7: "motor fault",
}


def next_low_oat_lockout(current, oat_f, disable_f=45.0, enable_f=50.0):
    """Apply pump lockout hysteresis; unknown startup OAT fails pump-safe."""
    if oat_f is None:
        return True if current is None else bool(current)
    if current is None:
        return float(oat_f) < float(enable_f)
    if not current and oat_f <= disable_f:
        return True
    if current and oat_f >= enable_f:
        return False
    return bool(current)


@dataclass(frozen=True)
class MS1Status:
    state: str
    powered: bool
    fault_active: bool
    fault_code: Optional[int]
    fault_description: str
    level: str
    volts: float
    last_high_age_seconds: Optional[float]
    last_transition_age_seconds: Optional[float]


class MS1Decoder:
    def __init__(
        self,
        low_volts=2.0,
        high_volts=7.0,
        debounce_seconds=0.2,
        pulse_group_gap_seconds=3.0,
        offline_seconds=20.0,
        fault_clear_high_seconds=15.0,
    ):
        self.low_volts = float(low_volts)
        self.high_volts = float(high_volts)
        self.debounce_seconds = float(debounce_seconds)
        self.pulse_group_gap_seconds = float(pulse_group_gap_seconds)
        self.offline_seconds = float(offline_seconds)
        self.fault_clear_high_seconds = float(fault_clear_high_seconds)

        self._candidate_level = "UNKNOWN"
        self._candidate_since = None
        self._stable_level = "UNKNOWN"
        self._stable_since = None
        self._last_transition_at = None
        self._last_high_at = None
        self._pending_pulses = 0
        self._last_pulse_at = None
        self._fault_active = False
        self._fault_code = None
        self._volts = 0.0

    def _observed_level(self, volts):
        if volts <= self.low_volts:
            return "LOW"
        if volts >= self.high_volts:
            return "HIGH"
        return "MID"

    def _accept_level(self, now, level):
        old_level = self._stable_level
        if level == old_level:
            return
        self._stable_level = level
        self._stable_since = now
        self._last_transition_at = now
        if level == "LOW" and old_level == "HIGH":
            self._pending_pulses += 1
            self._last_pulse_at = now

    def _finish_pulse_group(self, now):
        if (
            self._pending_pulses
            and self._stable_level == "HIGH"
            and self._last_pulse_at is not None
            and now - self._last_pulse_at >= self.pulse_group_gap_seconds
        ):
            self._fault_code = self._pending_pulses
            self._fault_active = True
            self._pending_pulses = 0

    def update(self, now, volts):
        now = float(now)
        self._volts = float(volts)
        observed = self._observed_level(self._volts)

        # The undefined middle band supplies Schmitt-style hysteresis.
        if observed != "MID":
            if observed != self._candidate_level:
                self._candidate_level = observed
                self._candidate_since = now
            elif (
                observed != self._stable_level
                and self._candidate_since is not None
                and now - self._candidate_since >= self.debounce_seconds
            ):
                self._accept_level(now, observed)

        if self._stable_level == "HIGH":
            self._last_high_at = now

        self._finish_pulse_group(now)

        # A fault clears only after a long, uninterrupted healthy indication.
        if (
            self._fault_active
            and self._stable_level == "HIGH"
            and self._last_pulse_at is not None
            and now - self._last_pulse_at >= self.fault_clear_high_seconds
        ):
            self._fault_active = False
            self._fault_code = None

        return self.status(now)

    def status(self, now):
        now = float(now)
        last_high_age = (
            None if self._last_high_at is None else max(0.0, now - self._last_high_at)
        )
        transition_age = (
            None
            if self._last_transition_at is None
            else max(0.0, now - self._last_transition_at)
        )
        low_long_enough = (
            self._stable_level == "LOW"
            and self._stable_since is not None
            and now - self._stable_since >= self.offline_seconds
        )
        powered = self._last_high_at is not None and not low_long_enough

        if low_long_enough:
            state = "OFFLINE"
            powered = False
        elif self._fault_active:
            state = "FAULT"
        elif powered:
            state = "READY"
        else:
            state = "UNKNOWN"

        description = ""
        if self._fault_code is not None:
            description = FAULT_DESCRIPTIONS.get(
                self._fault_code,
                "unknown fault pulse count",
            )

        return MS1Status(
            state=state,
            powered=powered,
            fault_active=self._fault_active,
            fault_code=self._fault_code,
            fault_description=description,
            level=self._stable_level,
            volts=self._volts,
            last_high_age_seconds=last_high_age,
            last_transition_age_seconds=transition_age,
        )
