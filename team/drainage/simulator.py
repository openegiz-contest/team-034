#!/usr/bin/env python3
"""
Drainage simulator for the «Кварцитовые Горки» digital twin (horizon 420 m).

Water flows into the main sump; enabled pumps pump it to the surface.
Every tick the simulator:
  1. reads the operator's controls from Ditto (pump enabled, inflow setpoint),
  2. steps the water balance,
  3. publishes the features to MQTT as a Ditto protocol "merge" command
     (topic telemetry/<twin>), so the "control" features written by the UI
     are never overwritten.

SKELETON: the parameters below are placeholders. Replace them with the
values from the mining project (PDF pp. 130-134) and mark the rest as
assumptions in SUBMISSION.md.
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

import paho.mqtt.client as mqtt

NAMESPACE = "org.kvgorki"
TOPIC_PREFIX = "telemetry"

# --- Parameters (TODO: take from the project PDF, pp. 130-134) -------------
SUMP_CAPACITY_M3 = 1600.0   # TODO from PDF
SUMP_AREA_M2 = 400.0        # TODO from PDF: level = volume / area
ALARM_PCT = 80.0            # assumption
WARNING_PCT = 60.0          # assumption
PUMP_FLOW_M3H = 300.0       # CNS 300-480 rated flow
PUMP_HEAD_M = 480.0         # CNS 300-480 rated head
PUMP_EFFICIENCY = 0.7       # assumption
START_VOLUME_M3 = 400.0     # assumption
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
    def __init__(self):
        self.volume = START_VOLUME_M3
        self.inflow = 400.0
        self.enabled = {p: True for p in PUMPS}
        self.hours = {p: 0.0 for p in PUMPS}

    def apply_controls(self, sump_control, pump_controls):
        if "inflow_m3h" in sump_control:
            self.inflow = max(0.0, float(sump_control["inflow_m3h"]))
        for pump, control in pump_controls.items():
            if "enabled" in control:
                self.enabled[pump] = bool(control["enabled"])

    def outflow(self):
        return sum(PUMP_FLOW_M3H for p in PUMPS if self.enabled[p])

    def step(self, dt_s):
        dt_h = dt_s / 3600
        # Pumps cannot pump more water than is in the sump.
        pumped = min(self.outflow() * dt_h, self.volume + self.inflow * dt_h)
        self.volume = min(SUMP_CAPACITY_M3, max(0.0, self.volume + self.inflow * dt_h - pumped))
        for p in PUMPS:
            if self.enabled[p]:
                self.hours[p] += dt_h

    def time_to_alarm_h(self):
        net = self.inflow - self.outflow()
        alarm_volume = SUMP_CAPACITY_M3 * ALARM_PCT / 100
        if self.volume >= alarm_volume:
            return 0.0
        if net <= 0:
            return -1.0  # water is not rising
        return (alarm_volume - self.volume) / net

    def snapshot(self):
        fill = 100 * self.volume / SUMP_CAPACITY_M3
        state = "alarm" if fill >= ALARM_PCT else "warning" if fill >= WARNING_PCT else "normal"
        # Hydraulic power P = rho * g * Q * H / eta
        power_kw = 1000 * 9.81 * (PUMP_FLOW_M3H / 3600) * PUMP_HEAD_M / PUMP_EFFICIENCY / 1000
        things = {
            "sump-01": {
                "volume": {"value": round(self.volume, 1), "unit": "m3"},
                "level": {"value": round(self.volume / SUMP_AREA_M2, 2), "unit": "m"},
                "fill_pct": {"value": round(fill, 1), "unit": "%"},
                "inflow": {"value": round(self.inflow, 1), "unit": "m3/h"},
                "outflow": {"value": round(self.outflow(), 1), "unit": "m3/h"},
                "time_to_alarm": {"value": round(self.time_to_alarm_h(), 2), "unit": "h"},
                "state": {"value": state},
            },
        }
        for p in PUMPS:
            on = self.enabled[p]
            things[p] = {
                "state": {"value": "running" if on else "stopped"},
                "flow": {"value": PUMP_FLOW_M3H if on else 0.0, "unit": "m3/h"},
                "power": {"value": round(power_kw if on else 0.0, 1), "unit": "kW"},
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

    client = None
    if not args.dry_run:
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
                     ", ".join(f"{p}:{'on' if sim.enabled[p] else 'off'}" for p in PUMPS))
        if args.steps and published >= args.steps:
            break
        time.sleep(args.interval)

    if client:
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
