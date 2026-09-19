import unittest

from hvac_modes import boiler_panel_interlock_should_block, describe_zone_mode


def describe(**overrides):
    values = {
        "heat": False,
        "cool": False,
        "fan": False,
        "post_cool_active": False,
        "post_heat_fan_suppressed": False,
        "warm_weather_shutdown": False,
        "cooler_state": "READY",
        "cooler_fault_code": None,
        "low_oat_lockout": False,
        "oat_known": True,
    }
    values.update(overrides)
    return describe_zone_mode(**values)


class ZoneModeDiagnosticTests(unittest.TestCase):
    def test_boiler_interlock_latches_main_floor_heat_mode(self):
        self.assertTrue(boiler_panel_interlock_should_block(None, False))
        self.assertTrue(boiler_panel_interlock_should_block("COOL", False))
        self.assertFalse(boiler_panel_interlock_should_block("HEAT", False))

    def test_boiler_interlock_wwsd_and_unknown_state_fail_safe(self):
        self.assertTrue(boiler_panel_interlock_should_block("HEAT", True))
        self.assertTrue(boiler_panel_interlock_should_block("HEAT", None))

    def test_ready_cooling_is_not_blocked(self):
        self.assertEqual(describe(cool=True), ("COOL", "COOL", "NONE"))

    def test_unknown_ms1_explains_startup_block(self):
        self.assertEqual(
            describe(cool=True, cooler_state="UNKNOWN"),
            ("COOL", "COOL_BLOCKED", "MS1_STARTUP_UNKNOWN"),
        )

    def test_offline_ms1_explains_cooling_block(self):
        self.assertEqual(
            describe(cool=True, cooler_state="OFFLINE"),
            ("COOL", "COOL_BLOCKED", "MS1_OFFLINE"),
        )

    def test_ms1_fault_includes_zero_padded_code(self):
        self.assertEqual(
            describe(cool=True, cooler_state="FAULT", cooler_fault_code=2),
            ("COOL", "COOL_BLOCKED", "MS1_FAULT_FC02"),
        )

    def test_low_oat_cooling_becomes_free_cooling(self):
        self.assertEqual(
            describe(cool=True, low_oat_lockout=True),
            ("COOL", "FREE_COOL", "LOW_OAT_PUMP_LOCKOUT"),
        )

    def test_unknown_oat_explains_pump_safe_free_cooling(self):
        self.assertEqual(
            describe(cool=True, low_oat_lockout=True, oat_known=False),
            ("COOL", "FREE_COOL", "OAT_UNKNOWN_PUMP_SAFE"),
        )

    def test_wwsd_explains_heat_block(self):
        self.assertEqual(
            describe(heat=True, warm_weather_shutdown=True),
            ("HEAT", "HEAT_BLOCKED", "WWSD_ACTIVE"),
        )

    def test_heat_cool_conflict_reports_heat_priority(self):
        self.assertEqual(
            describe(heat=True, cool=True),
            ("HEAT", "HEAT", "INPUT_CONFLICT_HEAT_PRIORITY"),
        )

    def test_manual_fan_call_is_valid_ventilation(self):
        self.assertEqual(
            describe(fan=True),
            ("VENT", "VENT", "NONE"),
        )

    def test_manual_fan_call_reports_ms1_block(self):
        self.assertEqual(
            describe(fan=True, cooler_state="OFFLINE"),
            ("VENT", "VENT_BLOCKED", "MS1_OFFLINE"),
        )

    def test_heat_ignores_accompanying_fan_input(self):
        self.assertEqual(
            describe(heat=True, fan=True),
            ("HEAT", "HEAT", "NONE"),
        )

    def test_post_heat_fan_is_explicitly_suppressed(self):
        self.assertEqual(
            describe(fan=True, post_heat_fan_suppressed=True),
            ("VENT", "OFF", "POST_HEAT_FAN_SUPPRESSED"),
        )

    def test_post_cool_vent_is_allowed(self):
        self.assertEqual(
            describe(fan=True, post_cool_active=True),
            ("VENT", "VENT", "NONE"),
        )

    def test_post_cool_vent_reports_ms1_block(self):
        self.assertEqual(
            describe(
                fan=True,
                post_cool_active=True,
                cooler_state="OFFLINE",
            ),
            ("VENT", "VENT_BLOCKED", "MS1_OFFLINE"),
        )


if __name__ == "__main__":
    unittest.main()
