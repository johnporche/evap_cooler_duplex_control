import unittest

from hvac_ms1 import MS1Decoder, next_low_oat_lockout


def hold(decoder, start, end, volts, step=0.1):
    now = start
    status = None
    while now <= end + 1e-9:
        status = decoder.update(now, volts)
        now += step
    return status


class MS1DecoderTests(unittest.TestCase):
    def test_low_oat_lockout_hysteresis_and_unknown_startup(self):
        self.assertTrue(next_low_oat_lockout(None, None))
        self.assertFalse(next_low_oat_lockout(None, 56.8))
        self.assertFalse(next_low_oat_lockout(False, 46.0))
        self.assertTrue(next_low_oat_lockout(False, 45.0))
        self.assertTrue(next_low_oat_lockout(True, 49.0))
        self.assertFalse(next_low_oat_lockout(True, 50.0))

    def test_high_signal_becomes_ready(self):
        decoder = MS1Decoder()
        status = hold(decoder, 0.0, 0.5, 10.7)
        self.assertEqual(status.state, "READY")
        self.assertTrue(status.powered)

    def test_short_low_pulse_does_not_look_offline(self):
        decoder = MS1Decoder()
        hold(decoder, 0.0, 1.0, 10.7)
        hold(decoder, 1.1, 1.6, 0.0)
        status = hold(decoder, 1.7, 2.5, 10.7)
        self.assertEqual(status.state, "READY")
        self.assertTrue(status.powered)

    def test_decodes_two_low_pulses_as_fc02(self):
        decoder = MS1Decoder()
        hold(decoder, 0.0, 1.0, 10.7)
        hold(decoder, 1.1, 1.5, 0.0)
        hold(decoder, 1.6, 2.0, 10.7)
        hold(decoder, 2.1, 2.5, 0.0)
        status = hold(decoder, 2.6, 5.5, 10.7)
        self.assertEqual(status.state, "FAULT")
        self.assertEqual(status.fault_code, 2)
        self.assertEqual(status.fault_description, "failure to detect water at probes")

    def test_continuous_low_becomes_offline(self):
        decoder = MS1Decoder(offline_seconds=5.0)
        hold(decoder, 0.0, 1.0, 10.7)
        status = hold(decoder, 1.1, 6.5, 0.0)
        self.assertEqual(status.state, "OFFLINE")
        self.assertFalse(status.powered)

    def test_middle_voltage_does_not_chatter(self):
        decoder = MS1Decoder()
        hold(decoder, 0.0, 1.0, 10.7)
        status = hold(decoder, 1.1, 3.0, 4.0)
        self.assertEqual(status.state, "READY")
        self.assertEqual(status.level, "HIGH")

    def test_fault_clears_after_continuous_high(self):
        decoder = MS1Decoder(fault_clear_high_seconds=6.0)
        hold(decoder, 0.0, 1.0, 10.7)
        hold(decoder, 1.1, 1.5, 0.0)
        status = hold(decoder, 1.6, 4.5, 10.7)
        self.assertEqual(status.state, "FAULT")
        status = hold(decoder, 4.6, 7.7, 10.7)
        self.assertEqual(status.state, "READY")
        self.assertIsNone(status.fault_code)


if __name__ == "__main__":
    unittest.main()
