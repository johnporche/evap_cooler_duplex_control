import unittest

from hvac_airflow import (
    dampers_require_startup_settle,
    next_post_cool_state,
    next_post_heat_fan_suppression,
    select_damper_commands,
    select_zone_airflow,
)


class ZoneAirflowTests(unittest.TestCase):
    def test_apartment_cooling_suppresses_first_floor_post_cool_vent(self):
        airflow = select_zone_airflow(False, True, True, False)
        self.assertEqual(airflow, (False, True))
        self.assertEqual(select_damper_commands(*airflow), (True, False))

    def test_first_floor_cooling_suppresses_apartment_post_cool_vent(self):
        airflow = select_zone_airflow(True, False, False, True)
        self.assertEqual(airflow, (True, False))
        self.assertEqual(select_damper_commands(*airflow), (False, True))

    def test_both_post_cool_vent_requests_keep_both_dampers_open(self):
        airflow = select_zone_airflow(False, False, True, True)
        self.assertEqual(airflow, (True, True))
        self.assertEqual(select_damper_commands(*airflow), (False, False))

    def test_both_cooling_requests_keep_both_dampers_open(self):
        airflow = select_zone_airflow(True, True, True, True)
        self.assertEqual(airflow, (True, True))
        self.assertEqual(select_damper_commands(*airflow), (False, False))

    def test_single_post_cool_vent_request_keeps_requesting_zone_open(self):
        airflow = select_zone_airflow(False, False, True, False)
        self.assertEqual(airflow, (True, False))
        self.assertEqual(select_damper_commands(*airflow), (False, True))

    def test_no_request_fails_safe_with_both_dampers_open(self):
        airflow = select_zone_airflow(False, False, False, False)
        self.assertEqual(airflow, (False, False))
        self.assertEqual(select_damper_commands(*airflow), (False, False))


class PostCoolStateTests(unittest.TestCase):
    def test_cooling_falling_edge_with_fan_starts_post_cool(self):
        self.assertEqual(
            next_post_cool_state(True, False, False, False, True),
            (False, True),
        )

    def test_post_cool_continues_while_fan_remains_on(self):
        self.assertEqual(
            next_post_cool_state(False, True, False, False, True),
            (False, True),
        )

    def test_fan_turning_off_ends_post_cool(self):
        self.assertEqual(
            next_post_cool_state(False, True, False, False, False),
            (False, False),
        )

    def test_later_manual_fan_call_does_not_start_post_cool(self):
        self.assertEqual(
            next_post_cool_state(False, False, False, False, True),
            (False, False),
        )

    def test_fan_call_at_controller_start_does_not_start_post_cool(self):
        self.assertEqual(
            next_post_cool_state(False, False, False, False, True),
            (False, False),
        )

    def test_heat_with_fan_clears_post_cool(self):
        self.assertEqual(
            next_post_cool_state(False, True, True, False, True),
            (False, False),
        )

    def test_heat_and_cool_conflict_cannot_arm_post_cool(self):
        self.assertEqual(
            next_post_cool_state(True, False, True, True, True),
            (False, False),
        )

    def test_vent_timeout_clears_post_cool(self):
        self.assertEqual(
            next_post_cool_state(False, True, False, False, True, True),
            (False, False),
        )


class PostHeatFanSuppressionTests(unittest.TestCase):
    def test_fan_remaining_on_when_heat_ends_is_suppressed(self):
        self.assertEqual(
            next_post_heat_fan_suppression(True, False, False, False, True),
            (False, True),
        )

    def test_suppression_remains_while_fan_remains_on(self):
        self.assertEqual(
            next_post_heat_fan_suppression(False, True, False, False, True),
            (False, True),
        )

    def test_fan_off_clears_suppression(self):
        self.assertEqual(
            next_post_heat_fan_suppression(False, True, False, False, False),
            (False, False),
        )

    def test_later_fresh_fan_call_is_not_suppressed(self):
        self.assertEqual(
            next_post_heat_fan_suppression(False, False, False, False, True),
            (False, False),
        )

    def test_cooling_clears_suppression(self):
        self.assertEqual(
            next_post_heat_fan_suppression(False, True, False, True, True),
            (False, False),
        )


class DamperSettleTests(unittest.TestCase):
    def test_vent_to_cooling_transition_waits_for_closing_damper(self):
        self.assertTrue(
            dampers_require_startup_settle(True, False, True, "VENT")
        )

    def test_running_cooling_does_not_interrupt_for_damper_change(self):
        self.assertFalse(
            dampers_require_startup_settle(True, False, True, "RUN")
        )

    def test_both_dampers_open_need_no_settle(self):
        self.assertFalse(
            dampers_require_startup_settle(False, False, True, "VENT")
        )


if __name__ == "__main__":
    unittest.main()
