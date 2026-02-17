"""
Demo Poller — emulates 2 generators (HGM9520N) and 1 ATS (HGM9560).

Generates realistic metrics and publishes to Redis in the same format
as the real ModbusPoller, so the frontend cannot tell the difference.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
from datetime import datetime, timezone

from redis.asyncio import Redis

from config import settings

logger = logging.getLogger("scada.demo_poller")

DEMO_DEVICES = [
    {"device_id": 1, "site_code": "MKZ", "device_type": "generator", "name": "Gen1", "power_base": 240, "phase": 0},
    {"device_id": 2, "site_code": "MKZ", "device_type": "generator", "name": "Gen2", "power_base": 210, "phase": 1.5},
    {"device_id": 3, "site_code": "MKZ", "device_type": "ats",       "name": "SPR"},
]


class DemoPoller:
    """Emulates Modbus devices. Generates realistic metrics and pushes to Redis."""

    def __init__(self, redis: Redis):
        self.redis = redis
        self._running = False
        self._tick = 0

    async def start(self) -> None:
        self._running = True
        logger.info("DemoPoller started — emulating %d devices", len(DEMO_DEVICES))

        while self._running:
            for cfg in DEMO_DEVICES:
                if cfg["device_type"] == "generator":
                    payload = self._gen_generator_metrics(cfg)
                else:
                    payload = self._gen_spr_metrics(cfg)
                await self._publish(payload)

            self._tick += 1
            await asyncio.sleep(settings.POLL_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        logger.info("DemoPoller stopped")

    async def _publish(self, payload: dict) -> None:
        json_str = json.dumps(payload, default=str)
        redis_key = f"device:{payload['device_id']}:metrics"
        await self.redis.set(redis_key, json_str)
        await self.redis.publish("metrics:updates", json_str)

    # ------------------------------------------------------------------
    # Generator (HGM9520N) metrics
    # ------------------------------------------------------------------

    def _gen_generator_metrics(self, device_cfg: dict) -> dict:
        t = self._tick
        phase = device_cfg.get("phase", 0)
        power_base = device_cfg.get("power_base", 240)
        noise = lambda amp=1.0: random.uniform(-amp, amp)

        base_power = power_base + 40 * math.sin(t * 0.02 + phase) + noise(5)

        base_voltage = 400
        gen_uab = base_voltage + noise(4)
        gen_ubc = base_voltage + noise(4)
        gen_uca = base_voltage + noise(4)
        gen_freq = 50.00 + noise(0.05)

        cos_phi = 0.85 + noise(0.02)
        current_per_phase = base_power / (math.sqrt(3) * base_voltage * cos_phi) * 1000 / 3
        current_a = current_per_phase + noise(2)
        current_b = current_per_phase + noise(2)
        current_c = current_per_phase + noise(2)

        power_per_phase = base_power / 3
        reactive_per_phase = base_power * 0.2 / 3

        engine_speed = 1500 + noise(3)
        coolant_temp = 82 + 3 * math.sin(t * 0.01 + phase) + noise(1)
        oil_pressure = 420 + noise(15)
        oil_temp = 95 + 2 * math.sin(t * 0.015 + phase) + noise(1)
        battery_volt = 27.6 + noise(0.3)
        fuel_level = max(20, 75 - t * 0.005 + noise(1))
        fuel_pressure = 350 + noise(10)
        turbo_pressure = 180 + noise(8)
        fuel_consumption = 45 + base_power * 0.08 + noise(2)

        run_hours = 1237 + t // 1800
        run_minutes = (t // 30) % 60
        start_count = 342
        energy_kwh = 456789 + int(t * base_power / 3600)

        return {
            "device_id": device_cfg["device_id"],
            "site_code": device_cfg["site_code"],
            "device_type": "generator",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "online": True,
            "error": None,

            "mode_auto": True,
            "mode_manual": False,
            "mode_stop": False,
            "mode_test": False,
            "alarm_common": False,
            "alarm_shutdown": False,
            "alarm_warning": False,
            "alarm_block": False,

            "mains_normal": True,
            "mains_load": True,
            "gen_normal": True,
            "gen_closed": True,

            "mains_uab": round(base_voltage + noise(3), 1),
            "mains_ubc": round(base_voltage + noise(3), 1),
            "mains_uca": round(base_voltage + noise(3), 1),
            "mains_freq": round(50.00 + noise(0.03), 2),

            "gen_uab": round(gen_uab, 1),
            "gen_ubc": round(gen_ubc, 1),
            "gen_uca": round(gen_uca, 1),
            "gen_freq": round(gen_freq, 2),
            "volt_diff": round(noise(1.5), 1),
            "freq_diff": round(noise(0.02), 2),
            "phase_diff": round(noise(2), 1),

            "current_a": round(current_a, 1),
            "current_b": round(current_b, 1),
            "current_c": round(current_c, 1),
            "current_earth": 0.0,

            "power_a": round(power_per_phase + noise(3), 1),
            "power_b": round(power_per_phase + noise(3), 1),
            "power_c": round(power_per_phase + noise(3), 1),
            "power_total": round(base_power, 1),
            "reactive_a": round(reactive_per_phase + noise(1), 1),
            "reactive_b": round(reactive_per_phase + noise(1), 1),
            "reactive_c": round(reactive_per_phase + noise(1), 1),
            "reactive_total": round(base_power * 0.2 + noise(2), 1),
            "pf_a": round(cos_phi + noise(0.005), 3),
            "pf_b": round(cos_phi + noise(0.005), 3),
            "pf_c": round(cos_phi + noise(0.005), 3),
            "pf_avg": round(cos_phi, 3),

            "engine_speed": round(engine_speed),
            "battery_volt": round(battery_volt, 1),
            "charger_volt": round(battery_volt + 0.5 + noise(0.2), 1),
            "coolant_temp": round(coolant_temp),
            "oil_pressure": round(oil_pressure),
            "fuel_level": round(fuel_level),
            "load_pct": round(base_power / 300 * 100),
            "oil_temp": round(oil_temp),
            "fuel_pressure": round(fuel_pressure),
            "turbo_pressure": round(turbo_pressure),
            "fuel_consumption": round(fuel_consumption, 1),

            "gen_status": 9,
            "gen_status_text": "running",
            "run_hours": run_hours,
            "run_minutes": run_minutes,
            "start_count": start_count,
            "energy_kwh": energy_kwh,
            "alarm_count": 0,
        }

    # ------------------------------------------------------------------
    # ATS / SPR (HGM9560) metrics
    # ------------------------------------------------------------------

    def _gen_spr_metrics(self, device_cfg: dict) -> dict:
        t = self._tick
        noise = lambda amp=1.0: random.uniform(-amp, amp)

        busbar_p = 450 + 60 * math.sin(t * 0.02) + noise(8)
        busbar_q = busbar_p * 0.2 + noise(3)

        base_v = 400
        busbar_uab = base_v + noise(3)
        busbar_ubc = base_v + noise(3)
        busbar_uca = base_v + noise(3)
        busbar_ua = base_v / math.sqrt(3) + noise(2)
        busbar_ub = base_v / math.sqrt(3) + noise(2)
        busbar_uc = base_v / math.sqrt(3) + noise(2)
        busbar_freq = 50.00 + noise(0.04)

        mains_uab = 400 + noise(5)
        mains_ubc = 400 + noise(5)
        mains_uca = 400 + noise(5)
        mains_ua = 231 + noise(3)
        mains_ub = 231 + noise(3)
        mains_uc = 231 + noise(3)
        mains_freq = 50.00 + noise(0.03)

        mains_ia = 120 + noise(5)
        mains_ib = 118 + noise(5)
        mains_ic = 122 + noise(5)

        mains_total_p = 180 + 20 * math.sin(t * 0.03) + noise(5)
        mains_total_q = mains_total_p * 0.15 + noise(2)

        busbar_current = busbar_p / (math.sqrt(3) * base_v) * 1000 + noise(3)
        battery_v = 27.5 + noise(0.3)

        return {
            "device_id": device_cfg["device_id"],
            "site_code": device_cfg["site_code"],
            "device_type": "ats",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "online": True,
            "error": None,

            "mode_auto": True,
            "mode_manual": False,
            "mode_stop": False,
            "mode_test": False,
            "alarm_common": False,
            "alarm_shutdown": False,
            "alarm_warning": False,
            "alarm_trip_stop": False,

            "genset_status": 9,
            "genset_status_text": "running",

            "mains_uab": round(mains_uab),
            "mains_ubc": round(mains_ubc),
            "mains_uca": round(mains_uca),
            "mains_ua": round(mains_ua),
            "mains_ub": round(mains_ub),
            "mains_uc": round(mains_uc),
            "mains_freq": round(mains_freq, 2),

            "busbar_uab": round(busbar_uab),
            "busbar_ubc": round(busbar_ubc),
            "busbar_uca": round(busbar_uca),
            "busbar_ua": round(busbar_ua),
            "busbar_ub": round(busbar_ub),
            "busbar_uc": round(busbar_uc),
            "busbar_freq": round(busbar_freq, 2),

            "mains_ia": round(mains_ia, 1),
            "mains_ib": round(mains_ib, 1),
            "mains_ic": round(mains_ic, 1),

            "mains_total_p": round(mains_total_p, 1),
            "mains_total_q": round(mains_total_q, 1),

            "busbar_current": round(busbar_current, 1),
            "battery_v": round(battery_v, 1),

            "busbar_p": round(busbar_p, 1),
            "busbar_q": round(busbar_q, 1),
            "busbar_switch": 3,
            "busbar_switch_text": "closed",
            "mains_status": 0,
            "mains_status_text": "normal",
            "mains_switch": 3,
            "mains_switch_text": "closed",

            "accum_kwh": round(45230 + t * 0.15, 1),
            "accum_kvarh": round(8920 + t * 0.03, 1),
            "maint_hours": max(0, 163 - t // 3600),
        }
