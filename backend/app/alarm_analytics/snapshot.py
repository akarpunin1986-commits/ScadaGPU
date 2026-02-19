"""Metrics snapshot builder — captures all current metrics at time of alarm.

Reads raw_data (the same dict published to Redis) and structures it into
a clean JSON snapshot for storage in alarm_analytics_events.metrics_snapshot.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("scada.alarm_analytics.snapshot")


# ---------------------------------------------------------------------------
# HGM9560 switch/status decode helpers
# ---------------------------------------------------------------------------

SWITCH_STATUS_TEXT = {
    0: "Synchronizing", 1: "Close delay", 2: "Wait closing",
    3: "Closed", 4: "Unloading", 5: "Open delay",
    6: "Wait opening", 7: "Opened",
}

MAINS_STATUS_TEXT = {
    0: "Normal", 1: "Normal delay", 2: "Abnormal", 3: "Abnormal delay",
}

GENSET_STATUS_9560_TEXT = {
    0: "Standby", 1: "Preheat", 2: "Fuel Output", 3: "Crank",
    4: "Crank Rest", 5: "Safety Run", 6: "Start Idle",
    7: "Warming Up", 8: "Wait Load", 9: "Normal Running",
    10: "Cooling", 11: "Stop Idle", 12: "ETS",
    13: "Wait Stop", 14: "Stop Failure",
}

GEN_STATUS_9520N_TEXT = {
    0: "Standby", 1: "Preheat", 2: "Fuel On", 3: "Cranking",
    4: "Crank Rest", 5: "Safety Run", 6: "Idle", 7: "Warming",
    8: "Wait Load", 9: "Running", 10: "Cooling", 11: "Idle Stop",
    12: "ETS", 13: "Wait Stop", 14: "Post Stop", 15: "Stop Failure",
}


def _safe_get(data: dict, key: str, default=None):
    """Get value from dict, return default if missing or None."""
    val = data.get(key)
    return val if val is not None else default


def _decode_mains_fault(reg44: int | None) -> dict:
    """Decode register 0044 mains fault detail bits."""
    if reg44 is None:
        return {}
    return {
        "abnormal": bool(reg44 & (1 << 0)),
        "overvoltage": bool(reg44 & (1 << 1)),
        "undervoltage": bool(reg44 & (1 << 2)),
        "overfrequency": bool(reg44 & (1 << 3)),
        "underfrequency": bool(reg44 & (1 << 4)),
        "loss_phase": bool(reg44 & (1 << 5)),
        "reverse_phase": bool(reg44 & (1 << 6)),
        "blackout": bool(reg44 & (1 << 7)),
    }


def _detect_mode(data: dict) -> str:
    """Detect controller mode from data flags."""
    if data.get("mode_auto"):
        return "auto"
    if data.get("mode_manual"):
        return "manual"
    if data.get("mode_test"):
        return "test"
    if data.get("mode_stop"):
        return "stop"
    return "unknown"


def build_snapshot_hgm9560(raw_data: dict) -> dict:
    """Build structured metrics snapshot for HGM9560 (SPR)."""
    g = _safe_get

    busbar_switch_val = g(raw_data, "busbar_switch")
    mains_switch_val = g(raw_data, "mains_switch")
    mains_status_val = g(raw_data, "mains_status")
    genset_status_val = g(raw_data, "genset_status")

    return {
        "mains": {
            "uab": g(raw_data, "mains_uab", 0),
            "ubc": g(raw_data, "mains_ubc", 0),
            "uca": g(raw_data, "mains_uca", 0),
            "ua": g(raw_data, "mains_ua", 0),
            "ub": g(raw_data, "mains_ub", 0),
            "uc": g(raw_data, "mains_uc", 0),
            "ia": g(raw_data, "mains_ia", 0),
            "ib": g(raw_data, "mains_ib", 0),
            "ic": g(raw_data, "mains_ic", 0),
            "freq": g(raw_data, "mains_freq", 0),
            "total_p": g(raw_data, "mains_total_p", 0),
            "total_q": g(raw_data, "mains_total_q", 0),
            "status": mains_status_val,
            "status_text": MAINS_STATUS_TEXT.get(mains_status_val, "Unknown") if mains_status_val is not None else "N/A",
        },
        "busbar": {
            "uab": g(raw_data, "busbar_uab", 0),
            "ubc": g(raw_data, "busbar_ubc", 0),
            "uca": g(raw_data, "busbar_uca", 0),
            "ua": g(raw_data, "busbar_ua", 0),
            "ub": g(raw_data, "busbar_ub", 0),
            "uc": g(raw_data, "busbar_uc", 0),
            "freq": g(raw_data, "busbar_freq", 0),
            "current": g(raw_data, "busbar_current", 0),
            "total_p": g(raw_data, "busbar_p", 0),
            "total_q": g(raw_data, "busbar_q", 0),
        },
        "switches": {
            "busbar_switch": busbar_switch_val,
            "busbar_switch_text": SWITCH_STATUS_TEXT.get(busbar_switch_val, "Unknown") if busbar_switch_val is not None else "N/A",
            "mains_switch": mains_switch_val,
            "mains_switch_text": SWITCH_STATUS_TEXT.get(mains_switch_val, "Unknown") if mains_switch_val is not None else "N/A",
            "mains_status": mains_status_val,
            "mains_status_text": MAINS_STATUS_TEXT.get(mains_status_val, "Unknown") if mains_status_val is not None else "N/A",
        },
        "genset_status": genset_status_val,
        "genset_status_text": GENSET_STATUS_9560_TEXT.get(genset_status_val, "Unknown") if genset_status_val is not None else "N/A",
        "battery_voltage": g(raw_data, "battery_v", 0),
        "mode": _detect_mode(raw_data),
        "indicators": g(raw_data, "indicators"),
        "mains_fault_detail": _decode_mains_fault(g(raw_data, "alarm_reg_44")),
    }


def build_snapshot_hgm9520n(raw_data: dict) -> dict:
    """Build structured metrics snapshot for HGM9520N (Generator)."""
    g = _safe_get

    gen_status_val = g(raw_data, "gen_status")

    return {
        "gen": {
            "uab": g(raw_data, "gen_uab", 0),
            "ubc": g(raw_data, "gen_ubc", 0),
            "uca": g(raw_data, "gen_uca", 0),
            "ua": round(g(raw_data, "gen_uab", 0) / 1.732, 0) if g(raw_data, "gen_uab") else 0,
            "ub": round(g(raw_data, "gen_ubc", 0) / 1.732, 0) if g(raw_data, "gen_ubc") else 0,
            "uc": round(g(raw_data, "gen_uca", 0) / 1.732, 0) if g(raw_data, "gen_uca") else 0,
            "ia": g(raw_data, "current_a", 0),
            "ib": g(raw_data, "current_b", 0),
            "ic": g(raw_data, "current_c", 0),
            "freq": g(raw_data, "gen_freq", 0),
            "total_p": g(raw_data, "power_total", 0),
            "total_q": g(raw_data, "reactive_total", 0),
            "engine_speed": g(raw_data, "engine_speed", 0),
        },
        "mains": {
            "uab": g(raw_data, "mains_uab", 0),
            "ubc": g(raw_data, "mains_ubc", 0),
            "uca": g(raw_data, "mains_uca", 0),
            "ua": round(g(raw_data, "mains_uab", 0) / 1.732, 0) if g(raw_data, "mains_uab") else 0,
            "ub": round(g(raw_data, "mains_ubc", 0) / 1.732, 0) if g(raw_data, "mains_ubc") else 0,
            "uc": round(g(raw_data, "mains_uca", 0) / 1.732, 0) if g(raw_data, "mains_uca") else 0,
            "freq": g(raw_data, "mains_freq", 0),
            "status": 0 if g(raw_data, "mains_normal") else 2,
            "status_text": "Normal" if g(raw_data, "mains_normal") else "Abnormal",
        },
        "battery_voltage": g(raw_data, "battery_volt", 0),
        "charger_voltage": g(raw_data, "charger_volt", 0),
        "oil_pressure": g(raw_data, "oil_pressure", 0),
        "coolant_temp": g(raw_data, "coolant_temp", 0),
        "fuel_level": g(raw_data, "fuel_level", 0),
        "engine_speed": g(raw_data, "engine_speed", 0),
        "genset_status": gen_status_val,
        "genset_status_text": GEN_STATUS_9520N_TEXT.get(gen_status_val, "Unknown") if gen_status_val is not None else "N/A",
        "mode": _detect_mode(raw_data),
    }


def build_snapshot(device_type: str, raw_data: dict) -> dict:
    """Build metrics snapshot for any device type."""
    try:
        if device_type == "ats":
            return build_snapshot_hgm9560(raw_data)
        elif device_type == "generator":
            return build_snapshot_hgm9520n(raw_data)
        else:
            return {"raw": {k: v for k, v in raw_data.items() if not k.startswith("alarm_")}}
    except Exception as exc:
        logger.error("Snapshot build error for %s: %s", device_type, exc)
        return {"error": str(exc)}
