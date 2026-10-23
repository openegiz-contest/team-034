"""Deterministic water balance for the Kvartsitovye Gorki sump."""
from dataclasses import dataclass
from math import isfinite

PUMP_CAPACITY_M3_H = 300.0

@dataclass
class WaterBalance:
    volume_m3: float
    inflow_m3_h: float
    pump1_on: bool = True
    pump2_on: bool = True

    def __post_init__(self):
        for name in ('volume_m3', 'inflow_m3_h'):
            value = getattr(self, name)
            if not isfinite(value) or value < 0:
                raise ValueError(f'{name} must be finite and nonnegative')

    def step(self, seconds: float) -> dict:
        if not isfinite(seconds) or seconds <= 0:
            raise ValueError('seconds must be finite and positive')
        if not isfinite(self.inflow_m3_h) or self.inflow_m3_h < 0:
            raise ValueError('inflow_m3_h must be finite and nonnegative')
        incoming = self.inflow_m3_h * seconds / 3600.0
        requested = PUMP_CAPACITY_M3_H * (self.pump1_on + self.pump2_on) * seconds / 3600.0
        available = self.volume_m3 + incoming
        pumped = min(available, requested)
        self.volume_m3 = max(0.0, available - pumped)
        return {
            'volume_m3': self.volume_m3,
            'inflow_m3_h': self.inflow_m3_h,
            'pump1_on': self.pump1_on,
            'pump2_on': self.pump2_on,
            'requested_outflow_m3_h': PUMP_CAPACITY_M3_H * (self.pump1_on + self.pump2_on),
            'actual_pumped_m3': pumped,
            'incoming_m3': incoming,
        }
