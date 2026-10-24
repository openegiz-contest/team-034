#!/usr/bin/env python3
"""
Drainage simulator for the «Кварцитовые Горки» digital twin (horizon 420 m).

Water flows into the main sump; enabled pumps pump it to the surface.
The water balance itself is the team's WaterBalance (water_balance.py).
Every tick the simulator:
  1. reads the operator's controls from Ditto (pump enabled, inflow setpoint),
  2. steps the water balance,
  3. publishes the features to MQTT as a Ditto protocol "merge" command
     (topic telemetry/<twin>), so the "control" features written by the UI
     are never overwritten.

Parameters come from the mining project (PDF pp. 131-134); the rest are
assumptions listed in SUBMISSION.md.
"""

import argparse
import base64
import json
import logging
import os
import signal
import sys
import time
import urllib.error
import urllib.request

from water_balance import WaterBalance

NAMESPACE = "org.kvgorki"
TOPIC_PREFIX = "telemetry"

# --- Parameters ---------------------------------------------------------------
# Source: Plan of mining operations, Kvartsitovye Gorki deposit, pp. 131-134
# (https://hearings.ndbecology.gov.kz/Public/PubHearings/LoadFile/239849).
PUMP_FLOW_M3H = 300.0         # p. 131: CNS 300x480, flow 300 m3/h
PUMP_HEAD_M = 480.0           # p. 131: head 480 m
PUMP_MOTOR_KW = 630.0         # p. 131: motor 630 kW (rating, used as a check)
NORMAL_INFLOW_M3H = 70.0      # p. 133: actual inflow at hor. 360-420 m did not exceed 65-70 m3/h
PROJECT_MAX_INFLOW_M3H = 108.0  # p. 133: maximum inflow incl. drilling and dust suppression
PUMP_OUT_HOURS = 20.0         # p. 133: working pumps must pump the daily inflow out in <= 20 h
# Assumptions (not in the project; see SUBMISSION.md, "Data and Assumptions"):
SUMP_CAPACITY_M3 = 4 * PROJECT_MAX_INFLOW_M3H  # 432 m3: 4 h of the maximum inflow
SUMP_AREA_M2 = 144.0          # level = volume / area, 3.0 m when full
STOP_PCT = 20.0               # level automation (p. 134 says pumps start/stop by level;
START_PCT = 50.0              #   the set points are ours)
ASSIST_PCT = 60.0             # second pump joins; also the warning level
WARNING_PCT = 60.0
ALARM_PCT = 80.0
PUMP_EFFICIENCY = 0.70        # CNS-type sectional pump, typical
MOTOR_EFFICIENCY = 0.94       # 6 kV induction motor, typical
START_VOLUME_M3 = 0.3 * SUMP_CAPACITY_M3
MAX_INFLOW_M3H = 2000.0       # input limit for the UI, not a mine value
PUMPS = ["pump-01", "pump-02"]

DITTO_URL = os.environ.get("DITTO_URL", "http://localhost:8080").rstrip("/")
DITTO_USER = os.environ.get("DITTO_USER", "ditto")
DITTO_PASSWORD = os.environ.get("DITTO_PASSWORD", "")
AUTH = "Basic " + base64.b64encode(f"{DITTO_USER}:{DITTO_PASSWORD}".encode()).decode()

log = logging.getLogger("drainage")


def read_control(name):
    """Control properties the UI wrote into Ditto, or {} if unavailable."""
    request = urllib.request.Request(
        f"{DITTO_URL}/api/2/things/{NAMESPACE}:{name}/features/control/properties",
        headers={"Authorization": AUTH},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        log.warning("cannot read control of %s: %s", name, exc)
        return {}


class Drainage:
    """The main sump around the team's WaterBalance.

    Adds what the mining project describes: the sump's capacity and levels,
    pumps that start and stop automatically by the water level with the
    second pump joining at a higher level, a failed pump replaced by the
    other one, and the pumps' electric power and energy.
    """

    def __init__(self):
        self.balance = WaterBalance(volume_m3=START_VOLUME_M3, inflow_m3_h=NORMAL_INFLOW_M3H,
                                    pump1_on=False, pump2_on=False)
        self.available = {p: True for p in PUMPS}  # False: failed / taken out by the operator
        self.hours = {p: 0.0 for p in PUMPS}
        self.energy_kwh = {p: 0.0 for p in PUMPS}
        self.cycle = False  # pumping from START_PCT down to STOP_PCT
        self.sim_hours = 0.0
        self.speedup = 1.0

    @property
    def volume(self):
        return self.balance.volume_m3

    @property
    def inflow(self):
        return self.balance.inflow_m3_h

    @property
    def running(self):
        return {"pump-01": self.balance.pump1_on, "pump-02": self.balance.pump2_on}

    def _set_running(self, pump, on):
        setattr(self.balance, "pump1_on" if pump == "pump-01" else "pump2_on", on)

    def fill_pct(self):
        return 100 * self.volume / SUMP_CAPACITY_M3

    def apply_controls(self, sump_control, pump_controls):
        if "inflow_m3h" in sump_control:
            try:
                inflow = float(sump_control["inflow_m3h"])
            except (TypeError, ValueError):
                inflow = None
            if inflow is not None and 0 <= inflow <= MAX_INFLOW_M3H:
                self.balance.inflow_m3_h = inflow
        for pump, control in pump_controls.items():
            if isinstance(control.get("enabled"), bool):
                self.available[pump] = control["enabled"]
        self.automate()

    def automate(self):
        """Level automation: start/stop by level, second pump at ASSIST_PCT."""
        for p in PUMPS:
            if not self.available[p]:
                self._set_running(p, False)
        fill = self.fill_pct()
        if fill <= STOP_PCT:
            self.cycle = False
        elif fill >= START_PCT:
            self.cycle = True
        ready = [p for p in PUMPS if self.available[p]]
        if not self.cycle:
            for p in PUMPS:
                self._set_running(p, False)
            return
        if fill >= ASSIST_PCT:
            wanted = len(ready)
        else:
            wanted = min(1, len(ready))
        running = [p for p in PUMPS if self.running[p]]
        # Lead pump: the one with fewer running hours, so the pumps wear evenly.
        for p in sorted(ready, key=lambda q: self.hours[q]):
            if len(running) >= wanted:
                break
            if p not in running:
                self._set_running(p, True)
                running.append(p)

    def pump_power_kw(self):
        # Electric power P = rho * g * Q * H / (eta_pump * eta_motor)
        return 1000 * 9.81 * (PUMP_FLOW_M3H / 3600) * PUMP_HEAD_M / PUMP_EFFICIENCY / MOTOR_EFFICIENCY / 1000

    def outflow(self):
        """Pumping rate the running pumps deliver (0 when the sump is empty)."""
        rated = PUMP_FLOW_M3H * sum(self.running.values())
        if self.volume <= 0:
            return min(rated, self.inflow)
        return rated

    def available_capacity(self):
        return PUMP_FLOW_M3H * sum(self.available.values())

    def required_capacity(self):
        """Rules of industrial safety: the daily inflow pumped out in 20 h."""
        return self.inflow * 24 / PUMP_OUT_HOURS

    def step(self, dt_s):
        self.automate()
        self.balance.step(dt_s)
        # The sump cannot hold more than its capacity: the rest floods the horizon.
        self.balance.volume_m3 = min(SUMP_CAPACITY_M3, self.balance.volume_m3)
        dt_h = dt_s / 3600
        self.sim_hours += dt_h
        for p, on in self.running.items():
            if on:
                self.hours[p] += dt_h
                self.energy_kwh[p] += self.pump_power_kw() * dt_h
        self.automate()

    def time_to_alarm_h(self):
        """Hours until the alarm level if the available pumps cannot keep up, else -1."""
        net = self.inflow - self.available_capacity()
        alarm_volume = SUMP_CAPACITY_M3 * ALARM_PCT / 100
        if self.volume >= alarm_volume:
            return 0.0
        if net <= 0:
            return -1.0
        return (alarm_volume - self.volume) / net

    def snapshot(self, now=None):
        fill = self.fill_pct()
        state = "alarm" if fill >= ALARM_PCT else "warning" if fill >= WARNING_PCT else "normal"
        things = {
            "sump-01": {
                "volume": {"value": round(self.volume, 1), "unit": "m3"},
                "level": {"value": round(self.volume / SUMP_AREA_M2, 2), "unit": "m"},
                "fill_pct": {"value": round(fill, 1), "unit": "%"},
                "inflow": {"value": round(self.inflow, 1), "unit": "m3/h"},
                "outflow": {"value": round(self.outflow(), 1), "unit": "m3/h"},
                "available_capacity": {"value": round(self.available_capacity(), 1), "unit": "m3/h"},
                "required_capacity": {"value": round(self.required_capacity(), 1), "unit": "m3/h"},
                "rules_ok": {"value": self.available_capacity() >= self.required_capacity()},
                "time_to_alarm": {"value": round(self.time_to_alarm_h(), 2), "unit": "h"},
                "state": {"value": state},
                "sim_hours": {"value": round(self.sim_hours, 3), "unit": "h"},
                "updated_at": {"value": round(time.time() if now is None else now, 1), "unit": "s"},
                "speedup": {"value": self.speedup, "unit": "x"},
            },
        }
        outflow = self.outflow()
        things["riser-01"] = {
            "flow": {"value": round(outflow, 1), "unit": "m3/h"},
            "state": {"value": "flowing" if outflow > 0 else "idle"},
        }
        for p in PUMPS:
            on = self.running[p]
            things[p] = {
                "state": {"value": "running" if on else "standby" if self.available[p] else "off"},
                "flow": {"value": PUMP_FLOW_M3H if on else 0.0, "unit": "m3/h"},
                "power": {"value": round(self.pump_power_kw() if on else 0.0, 1), "unit": "kW"},
                "energy": {"value": round(self.energy_kwh[p], 1), "unit": "kWh"},
                "hours": {"value": round(self.hours[p], 2), "unit": "h"},
            }
        return things


def ditto_merge_features(name, features):
    """A Ditto protocol merge command updating some features of one twin.

    Merge (not modify) leaves the other features, such as "control" written
    by the UI, untouched. All features go in one message under /features so
    Telegraf stores them as value_<feature>_properties_value.
    """
    return {
        "topic": f"{NAMESPACE}/{name}/things/twin/commands/merge",
        "headers": {"content-type": "application/merge-patch+json"},
        "path": "/features",
        "value": {feature: {"properties": props} for feature, props in features.items()},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mqtt-host", default=os.environ.get("MQTT_HOST", "localhost"))
    p.add_argument("--mqtt-port", type=int, default=int(os.environ.get("MQTT_PORT", "1883")))
    p.add_argument("--interval", type=float, default=float(os.environ.get("SIM_INTERVAL", "2")),
                   help="real seconds between publishes (default 2)")
    p.add_argument("--speedup", type=float, default=float(os.environ.get("SIM_SPEEDUP", "60")),
                   help="simulated seconds per real second (default 60)")
    p.add_argument("--dry-run", action="store_true", help="print messages instead of publishing")
    p.add_argument("--steps", type=int, default=0, help="stop after N publishes (0 = run forever)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sim = Drainage()
    sim.speedup = args.speedup

    client = None
    if not args.dry_run:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"kvgorki-drainage-{os.getpid()}")
        for attempt in range(30):
            try:
                client.connect(args.mqtt_host, args.mqtt_port, keepalive=30)
                break
            except OSError as exc:
                log.warning("MQTT %s:%s not reachable (%s), retrying", args.mqtt_host, args.mqtt_port, exc)
                time.sleep(2)
        else:
            log.error("giving up on MQTT %s:%s", args.mqtt_host, args.mqtt_port)
            return 1
        client.loop_start()

    stop = False

    def on_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    published = 0
    while not stop:
        if not args.dry_run:
            sim.apply_controls(read_control("sump-01"), {p: read_control(p) for p in PUMPS})
        sim.step(args.interval * args.speedup)
        for name, features in sim.snapshot().items():
            message = json.dumps(ditto_merge_features(name, features))
            if client:
                client.publish(f"{TOPIC_PREFIX}/{name}", message, qos=0)
            elif published == 0 or args.steps:
                print(message)
        published += 1
        if published % 15 == 0 or args.dry_run:
            s = sim.snapshot()["sump-01"]
            log.info("volume %7.1f m3 (%5.1f %%) | in %5.0f out %5.0f m3/h | to alarm %s h | %s",
                     s["volume"]["value"], s["fill_pct"]["value"], s["inflow"]["value"],
                     s["outflow"]["value"], s["time_to_alarm"]["value"],
                     ", ".join(f"{p}:{'run' if sim.running[p] else 'ready' if sim.available[p] else 'off'}" for p in PUMPS))
        if args.steps and published >= args.steps:
            break
        time.sleep(args.interval)

    if client:
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
