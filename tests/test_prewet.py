import unittest

from hvac_prewet import select_prewet


class PrewetTests(unittest.TestCase):
    def test_first_start_is_long(self):
        self.assertEqual(select_prewet(None, 75), (90.0, "first_start"))

    def test_restart_within_five_minutes_is_minimum(self):
        self.assertEqual(select_prewet(5 * 60, 95), (5.0, "immediate_restart"))

    def test_restart_between_five_and_thirty_minutes_is_short(self):
        self.assertEqual(select_prewet(20 * 60, 75), (15.0, "pads_recently_wet"))

    def test_hot_recent_restart_is_promoted_to_normal(self):
        self.assertEqual(select_prewet(20 * 60, 90), (60.0, "recent_restart_hot"))

    def test_restart_between_thirty_and_sixty_minutes_is_normal(self):
        self.assertEqual(select_prewet(45 * 60, 65), (60.0, "normal_restart"))

    def test_restart_after_sixty_minutes_is_long(self):
        self.assertEqual(select_prewet(60 * 60, 65), (90.0, "pads_likely_dry"))

    def test_unknown_oat_uses_time_window(self):
        self.assertEqual(select_prewet(20 * 60, None), (15.0, "pads_recently_wet"))


if __name__ == "__main__":
    unittest.main()
