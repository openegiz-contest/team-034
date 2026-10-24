import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import simulator as sim


def run(d, hours, step_s=60):
    for _ in range(int(hours * 3600 / step_s)):
        d.step(step_s)


class DrainageTests(unittest.TestCase):
    def test_project_numbers(self):
        self.assertEqual(sim.SUMP_CAPACITY_M3, 432)
        d = sim.Drainage()
        # Electric power of one pump stays below its 630 kW motor rating.
        self.assertLess(d.pump_power_kw(), sim.PUMP_MOTOR_KW)
        self.assertGreater(d.pump_power_kw(), 500)
        # Rules of industrial safety, as computed on p. 133: 108 * 24 / 20 = 129.6 m3/h.
        d.apply_controls({"inflow_m3h": 108}, {})
        self.assertAlmostEqual(d.required_capacity(), 129.6)

    def test_pumps_start_and_stop_by_level(self):
        d = sim.Drainage()  # starts at 30 %, below the start level
        self.assertFalse(any(d.running.values()))
        run(d, 1.5)  # 70 m3/h fills 105 m3: past 50 %
        self.assertEqual(sum(d.running.values()), 1)
        lowest = 100.0
        for _ in range(60):  # one pump (net -230 m3/h) empties the sump to 20 % and stops
            d.step(60)
            lowest = min(lowest, d.fill_pct())
        self.assertFalse(any(d.running.values()))
        self.assertLessEqual(lowest, sim.STOP_PCT + 1)
        self.assertLess(d.fill_pct(), sim.START_PCT)

    def test_second_pump_joins_at_assist_level(self):
        d = sim.Drainage()
        d.apply_controls({"inflow_m3h": 1000}, {})
        run(d, 0.2)
        self.assertEqual(sum(d.running.values()), 2)

    def test_lead_pump_alternates(self):
        d = sim.Drainage()
        leads = set()
        for _ in range(6 * 60):
            d.step(60)
            leads.update(p for p, on in d.running.items() if on)
        self.assertEqual(leads, {"pump-01", "pump-02"})

    def test_failed_pump_is_replaced(self):
        d = sim.Drainage()
        d.apply_controls({}, {"pump-01": {"enabled": False}})
        run(d, 1.5)
        self.assertEqual(d.running, {"pump-01": False, "pump-02": True})
        # One pump (300) still covers the normal inflow and the rules (84 m3/h).
        self.assertEqual(d.time_to_alarm_h(), -1.0)
        self.assertEqual(d.snapshot()["sump-01"]["rules_ok"]["value"], True)
        self.assertEqual(d.snapshot()["pump-01"]["state"]["value"], "off")

    def test_power_outage_gives_time_to_alarm(self):
        d = sim.Drainage()
        d.apply_controls({}, {"pump-01": {"enabled": False}, "pump-02": {"enabled": False}})
        expected = (sim.SUMP_CAPACITY_M3 * sim.ALARM_PCT / 100 - sim.START_VOLUME_M3) / sim.NORMAL_INFLOW_M3H
        self.assertAlmostEqual(d.time_to_alarm_h(), expected)
        run(d, 10)
        self.assertEqual(d.volume, sim.SUMP_CAPACITY_M3)
        self.assertEqual(d.snapshot()["sump-01"]["state"]["value"], "alarm")

    def test_breakthrough_needs_both_pumps(self):
        d = sim.Drainage()
        d.apply_controls({"inflow_m3h": 3 * sim.PROJECT_MAX_INFLOW_M3H}, {})
        self.assertEqual(d.time_to_alarm_h(), -1.0)
        d.apply_controls({}, {"pump-01": {"enabled": False}})
        self.assertGreater(d.time_to_alarm_h(), 0)
        self.assertEqual(d.snapshot()["sump-01"]["rules_ok"]["value"], False)

    def test_bad_controls_are_ignored(self):
        d = sim.Drainage()
        d.apply_controls({"inflow_m3h": "abc"}, {"pump-01": {"enabled": "no"}})
        d.apply_controls({"inflow_m3h": -5}, {})
        self.assertEqual(d.inflow, sim.NORMAL_INFLOW_M3H)
        self.assertTrue(d.available["pump-01"])

    def test_energy_counts_only_running_time(self):
        d = sim.Drainage()
        run(d, 3)
        for p in sim.PUMPS:
            self.assertAlmostEqual(d.energy_kwh[p], d.hours[p] * d.pump_power_kw(), places=3)


if __name__ == "__main__":
    unittest.main()
