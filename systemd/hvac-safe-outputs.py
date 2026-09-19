#!/usr/bin/python3
"""Synchronously place all HVAC outputs in their fail-safe state."""

import revpimodio2


SAFE_OUTPUTS = (
    "T_AO6_ANALOG_FAN_SPEED_DRV",
    "T_AO7_BMS_PUMP_ON",
    "T_AO8_BMS_SYS_ON",
    "T_R1_FRST_DMP_CLOSE",
    "T_R2_APT_DMP_CLOSE",
    "T_R3_FRST_BOILER",
    "T_R4_APT_BOILER",
)


def main():
    rpi = revpimodio2.RevPiModIO(autorefresh=False)
    try:
        for name in SAFE_OUTPUTS:
            rpi.io[name].value = 0
        # This oddly named LED channel drives an active-low boiler-panel
        # interlock. A process-image value of 0 blocks auxiliary thermostats.
        rpi.io.T_RevPiLED_WWSD.value = 0
        if not rpi.writeprocimg():
            raise RuntimeError("failed to write one or more safe outputs")
    finally:
        rpi.exit(full=True)


if __name__ == "__main__":
    main()
