import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from water_balance import WaterBalance

class WaterBalanceTests(unittest.TestCase):
    def test_both_on(self):
        self.assertAlmostEqual(WaterBalance(100, 400).step(60)['volume_m3'], 96.6666666667)
    def test_one_off(self):
        self.assertAlmostEqual(WaterBalance(100, 400, True, False).step(60)['volume_m3'], 101.6666666667)
    def test_both_off(self):
        self.assertAlmostEqual(WaterBalance(100, 400, False, False).step(60)['volume_m3'], 106.6666666667)
    def test_cannot_pump_more_than_available(self):
        result = WaterBalance(1, 0).step(60)
        self.assertEqual(result['volume_m3'], 0)
        self.assertEqual(result['actual_pumped_m3'], 1)
    def test_switch_during_run(self):
        model = WaterBalance(100, 400)
        model.step(60)
        model.pump2_on = False
        self.assertAlmostEqual(model.step(60)['volume_m3'], 98.3333333333)

if __name__ == '__main__':
    unittest.main()
