import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import simulator as sim


class DrainageTests(unittest.TestCase):
    def test_both_pumps_lower_the_water(self):
        d = sim.Drainage()
        d.step(3600)
        self.assertAlmostEqual(d.volume, sim.START_VOLUME_M3 + sim.NORMAL_INFLOW_M3H - 2 * sim.PUMP_FLOW_M3H)
        self.assertEqual(d.time_to_alarm_h(), -1.0)

    def test_one_pump_failure_gives_time_to_alarm(self):
        d = sim.Drainage()
        d.apply_controls({}, {"pump-02": {"enabled": False}})
        net = sim.NORMAL_INFLOW_M3H - sim.PUMP_FLOW_M3H
        expected = (sim.SUMP_CAPACITY_M3 * sim.ALARM_PCT / 100 - sim.START_VOLUME_M3) / net
        self.assertAlmostEqual(d.time_to_alarm_h(), expected)

    def test_volume_never_exceeds_capacity(self):
        d = sim.Drainage()
        d.apply_controls({}, {"pump-01": {"enabled": False}, "pump-02": {"enabled": False}})
        d.step(3600 * 100)
        self.assertEqual(d.volume, sim.SUMP_CAPACITY_M3)
        self.assertEqual(d.snapshot()["sump-01"]["state"]["value"], "alarm")

    def test_bad_controls_are_ignored(self):
        d = sim.Drainage()
        d.apply_controls({"inflow_m3h": "abc"}, {"pump-01": {"enabled": "no"}})
        d.apply_controls({"inflow_m3h": -5}, {})
        self.assertEqual(d.inflow, sim.NORMAL_INFLOW_M3H)
        self.assertTrue(d.enabled["pump-01"])

    def test_empty_sump_pumps_only_the_inflow(self):
        d = sim.Drainage()
        d.apply_controls({"inflow_m3h": 100}, {})
        d.step(3600 * 10)
        self.assertEqual(d.volume, 0)
        self.assertEqual(d.outflow(), 100)

    def test_stopped_pump_draws_no_power(self):
        d = sim.Drainage()
        d.apply_controls({}, {"pump-01": {"enabled": False}})
        snap = d.snapshot()
        self.assertEqual(snap["pump-01"]["power"]["value"], 0)
        self.assertGreater(snap["pump-02"]["power"]["value"], 500)


if __name__ == "__main__":
    unittest.main()
