"""
Phase 2 — Modbus Poller: фоновый опрос контроллеров Smartgen.

HGM9520N — Modbus TCP (pymodbus AsyncModbusTcpClient)
HGM9560  — Modbus RTU over TCP (raw asyncio socket + CRC16)
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time as _time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from pymodbus.client import AsyncModbusTcpClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from models.device import Device, ModbusProtocol

logger = logging.getLogger("scada.poller")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NO_DATA_VALUE = 32766


def _signed16(val: int) -> int:
    return val - 65536 if val > 32767 else val


def _signed32(lsb: int, msb: int) -> int:
    val = msb * 65536 + lsb
    return val - 0x100000000 if val > 0x7FFFFFFF else val


def _no_data_or(raw: int, converted: float) -> float | None:
    return None if raw >= 32000 or raw == NO_DATA_VALUE else converted


def _is_bad_temp(raw: int) -> bool:
    s = _signed16(raw)
    return raw == NO_DATA_VALUE or raw >= 32000 or s > 200 or s < -50


def _safe_load(raw: int) -> int | None:
    if raw == NO_DATA_VALUE or raw >= 32000:
        return None
    s = _signed16(raw)
    return None if s > 150 or s < -50 else s


# ---------------------------------------------------------------------------
# CRC-16/Modbus (for HGM9560 RTU over TCP)
# ---------------------------------------------------------------------------

def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_read_registers(slave: int, start: int, count: int) -> bytes:
    frame = struct.pack(">BBhH", slave, 0x03, start, count)
    crc = crc16_modbus(frame)
    return frame + struct.pack("<H", crc)


def build_write_coil(slave: int, address: int, value: bool) -> bytes:
    """FC05 — Write Single Coil (FF00=ON, 0000=OFF)."""
    data_val = 0xFF00 if value else 0x0000
    frame = struct.pack(">BBHH", slave, 0x05, address, data_val)
    crc = crc16_modbus(frame)
    return frame + struct.pack("<H", crc)


def build_write_register(slave: int, address: int, value: int) -> bytes:
    """FC06 — Write Single Register."""
    frame = struct.pack(">BBHH", slave, 0x06, address, value & 0xFFFF)
    crc = crc16_modbus(frame)
    return frame + struct.pack("<H", crc)


def _validate_write_echo(sent_frame: bytes, response: bytes, fc_name: str) -> None:
    """Validate FC05/FC06 echo response: CRC + address + value match."""
    if len(response) < 8:
        raise ConnectionError(f"{fc_name} short response ({len(response)} bytes): {response.hex()}")
    if response[1] & 0x80:
        error_code = response[2] if len(response) > 2 else 0
        raise ConnectionError(f"{fc_name} error response (exception code {error_code}): {response.hex()}")
    # Validate CRC of echo
    payload = response[:6]
    crc_received = struct.unpack("<H", response[6:8])[0]
    crc_calculated = crc16_modbus(payload)
    if crc_received != crc_calculated:
        raise ConnectionError(
            f"{fc_name} CRC mismatch: received 0x{crc_received:04X}, "
            f"calculated 0x{crc_calculated:04X}, raw={response.hex()}"
        )
    # Validate that echo matches the sent frame (slave + fc + addr + value)
    if response[:6] != sent_frame[:6]:
        raise ConnectionError(
            f"{fc_name} echo mismatch: sent={sent_frame[:6].hex()}, got={response[:6].hex()}"
        )


def parse_read_registers_response(data: bytes) -> list[int] | None:
    if len(data) < 5:
        return None
    _slave, fc, byte_count = struct.unpack(">BBB", data[:3])
    if fc & 0x80:
        return None
    expected_len = 3 + byte_count + 2
    if len(data) < expected_len:
        return None
    payload = data[:3 + byte_count]
    crc_received = struct.unpack("<H", data[3 + byte_count : 3 + byte_count + 2])[0]
    if crc16_modbus(payload) != crc_received:
        return None
    n_regs = byte_count // 2
    values = []
    for i in range(n_regs):
        val = struct.unpack(">H", data[3 + i * 2 : 5 + i * 2])[0]
        values.append(val)
    return values


# ---------------------------------------------------------------------------
# Register Maps
# ---------------------------------------------------------------------------

REGISTER_MAP_9520N: dict[str, dict] = {
    "status": {
        "address": 0, "count": 1,
        "fields": {
            "mode_auto":      lambda regs: bool(regs[0] & (1 << 9)),
            "mode_manual":    lambda regs: bool(regs[0] & (1 << 10)),
            "mode_stop":      lambda regs: bool(regs[0] & (1 << 11)),
            "mode_test":      lambda regs: bool(regs[0] & (1 << 8)),
            "alarm_common":   lambda regs: bool(regs[0] & (1 << 0)),
            "alarm_shutdown": lambda regs: bool(regs[0] & (1 << 1)),
            "alarm_warning":  lambda regs: bool(regs[0] & (1 << 2)),
            "alarm_block":    lambda regs: bool(regs[0] & (1 << 7)),
        },
    },
    "breaker": {
        "address": 114, "count": 1,
        "fields": {
            "mains_normal": lambda regs: bool(regs[0] & (1 << 0)),
            "mains_load":   lambda regs: bool(regs[0] & (1 << 1)),
            "gen_normal":   lambda regs: bool(regs[0] & (1 << 2)),
            "gen_closed":   lambda regs: bool(regs[0] & (1 << 3)),
        },
    },
    "mains_voltage": {
        "address": 120, "count": 16,
        "fields": {
            "mains_uab":  lambda regs: (regs[1] * 65536 + regs[0]) * 0.1,
            "mains_ubc":  lambda regs: (regs[3] * 65536 + regs[2]) * 0.1,
            "mains_uca":  lambda regs: (regs[5] * 65536 + regs[4]) * 0.1,
            "mains_freq": lambda regs: regs[15] * 0.01,
        },
    },
    "gen_voltage": {
        "address": 140, "count": 19,
        "fields": {
            "gen_uab":    lambda regs: (regs[1] * 65536 + regs[0]) * 0.1,
            "gen_ubc":    lambda regs: (regs[3] * 65536 + regs[2]) * 0.1,
            "gen_uca":    lambda regs: (regs[5] * 65536 + regs[4]) * 0.1,
            "gen_freq":   lambda regs: regs[15] * 0.01,
            "volt_diff":  lambda regs: _signed16(regs[16]) * 0.1,
            "freq_diff":  lambda regs: _signed16(regs[17]) * 0.01,
            "phase_diff": lambda regs: _signed16(regs[18]) * 0.1,
        },
    },
    "power_limit": {
        "address": 159, "count": 4,
        "fields": {
            "current_p_pct": lambda regs: _signed16(regs[0]) * 0.1,   # reg 0159
            "target_p_pct":  lambda regs: _signed16(regs[1]) * 0.1,   # reg 0160
            "current_q_pct": lambda regs: _signed16(regs[2]) * 0.1,   # reg 0161
            "target_q_pct":  lambda regs: _signed16(regs[3]) * 0.1,   # reg 0162
        },
    },
    "gen_current": {
        "address": 166, "count": 8,
        "fields": {
            "current_a":     lambda regs: _no_data_or(regs[0], regs[0] * 0.1),
            "current_b":     lambda regs: _no_data_or(regs[1], regs[1] * 0.1),
            "current_c":     lambda regs: _no_data_or(regs[2], regs[2] * 0.1),
            "current_earth": lambda regs: _no_data_or(regs[3], regs[3] * 0.1),
        },
    },
    "power": {
        "address": 174, "count": 28,
        "fields": {
            "power_a":        lambda regs: _signed32(regs[0], regs[1]) * 0.1,
            "power_b":        lambda regs: _signed32(regs[2], regs[3]) * 0.1,
            "power_c":        lambda regs: _signed32(regs[4], regs[5]) * 0.1,
            "power_total":    lambda regs: _signed32(regs[6], regs[7]) * 0.1,
            "reactive_a":     lambda regs: _signed32(regs[8], regs[9]) * 0.1,
            "reactive_b":     lambda regs: _signed32(regs[10], regs[11]) * 0.1,
            "reactive_c":     lambda regs: _signed32(regs[12], regs[13]) * 0.1,
            "reactive_total": lambda regs: _signed32(regs[14], regs[15]) * 0.1,
            "pf_a":           lambda regs: _signed16(regs[24]) * 0.001,
            "pf_b":           lambda regs: _signed16(regs[25]) * 0.001,
            "pf_c":           lambda regs: _signed16(regs[26]) * 0.001,
            "pf_avg":         lambda regs: _signed16(regs[27]) * 0.001,
        },
    },
    "engine": {
        "address": 212, "count": 30,
        "fields": {
            "engine_speed":     lambda regs: None if regs[0] > 5000 or regs[0] == 32766 else regs[0],
            "battery_volt":     lambda regs: _no_data_or(regs[1], regs[1] * 0.1),
            "charger_volt":     lambda regs: _no_data_or(regs[2], regs[2] * 0.1),
            "coolant_temp":     lambda regs: None if _is_bad_temp(regs[8]) else _signed16(regs[8]),
            "oil_pressure":     lambda regs: None if regs[10] >= 10000 or regs[10] == 32766 else regs[10],
            "fuel_level":       lambda regs: None if regs[12] > 100 or regs[12] == 32766 else regs[12],
            "load_pct":         lambda regs: _safe_load(regs[20]),
            "oil_temp":         lambda regs: None if _is_bad_temp(regs[22]) else _signed16(regs[22]),
            "fuel_pressure":    lambda regs: None if regs[24] >= 10000 or regs[24] == 32766 else regs[24],
            "turbo_pressure":   lambda regs: None if regs[28] >= 10000 or regs[28] == 32766 else regs[28],
            "fuel_consumption": lambda regs: None if regs[29] > 10000 or regs[29] == 32766 else regs[29] * 0.1,
        },
    },
    "accumulated": {
        "address": 260, "count": 16,
        "fields": {
            "gen_status":  lambda regs: regs[0],
            "run_hours":   lambda regs: regs[10],
            "run_minutes": lambda regs: regs[11],
            "start_count": lambda regs: regs[13],
            "energy_kwh":  lambda regs: regs[15] * 65536 + regs[14],
        },
    },
    "alarms": {
        "address": 511, "count": 1,
        "fields": {
            "alarm_count": lambda regs: regs[0],
        },
    },
    # Detailed alarm data table: 7 groups × 15 registers (addresses 1-105)
    # Shutdown(1), Trip&Stop(16), Trip(31), SafetyT&S(46), SafetyTrip(61), Block(76), Warning(91)
    "alarm_detail": {
        "address": 1, "count": 105,
        "fields": {
            # Shutdown group (base 1, offsets 0-5)
            "alarm_sd_0": lambda regs: regs[0],
            "alarm_sd_1": lambda regs: regs[1],
            "alarm_sd_2": lambda regs: regs[2],
            "alarm_sd_3": lambda regs: regs[3],
            "alarm_sd_4": lambda regs: regs[4],
            "alarm_sd_5": lambda regs: regs[5],
            # Trip & Stop group (base 16, offsets 0-5)
            "alarm_ts_0": lambda regs: regs[15],
            "alarm_ts_1": lambda regs: regs[16],
            "alarm_ts_2": lambda regs: regs[17],
            "alarm_ts_3": lambda regs: regs[18],
            "alarm_ts_4": lambda regs: regs[19],
            "alarm_ts_5": lambda regs: regs[20],
            # Trip group (base 31, offsets 0-5)
            "alarm_tr_0": lambda regs: regs[30],
            "alarm_tr_1": lambda regs: regs[31],
            "alarm_tr_2": lambda regs: regs[32],
            "alarm_tr_3": lambda regs: regs[33],
            "alarm_tr_4": lambda regs: regs[34],
            "alarm_tr_5": lambda regs: regs[35],
            # Block group (base 76, offsets 0-5)
            "alarm_bk_0": lambda regs: regs[75],
            "alarm_bk_1": lambda regs: regs[76],
            "alarm_bk_2": lambda regs: regs[77],
            "alarm_bk_3": lambda regs: regs[78],
            "alarm_bk_4": lambda regs: regs[79],
            "alarm_bk_5": lambda regs: regs[80],
            # Warning group (base 91, offsets 0-5)
            "alarm_wn_0": lambda regs: regs[90],
            "alarm_wn_1": lambda regs: regs[91],
            "alarm_wn_2": lambda regs: regs[92],
            "alarm_wn_3": lambda regs: regs[93],
            "alarm_wn_4": lambda regs: regs[94],
            "alarm_wn_5": lambda regs: regs[95],
        },
    },
}

# RTU-friendly version: alarm_detail (105 regs) split into 5 smaller blocks
# for reliable transfer over RS485 converters.
REGISTER_MAP_9520N_RTU: dict[str, dict] = {
    "status": {
        "address": 0, "count": 1,
        "fields": {
            "mode_auto":      lambda regs: bool(regs[0] & (1 << 9)),
            "mode_manual":    lambda regs: bool(regs[0] & (1 << 10)),
            "mode_stop":      lambda regs: bool(regs[0] & (1 << 11)),
            "mode_test":      lambda regs: bool(regs[0] & (1 << 8)),
            "alarm_common":   lambda regs: bool(regs[0] & (1 << 0)),
            "alarm_shutdown": lambda regs: bool(regs[0] & (1 << 1)),
            "alarm_warning":  lambda regs: bool(regs[0] & (1 << 2)),
            "alarm_block":    lambda regs: bool(regs[0] & (1 << 7)),
        },
    },
    "breaker": {
        "address": 114, "count": 1,
        "fields": {
            "mains_normal": lambda regs: bool(regs[0] & (1 << 0)),
            "mains_load":   lambda regs: bool(regs[0] & (1 << 1)),
            "gen_normal":   lambda regs: bool(regs[0] & (1 << 2)),
            "gen_closed":   lambda regs: bool(regs[0] & (1 << 3)),
        },
    },
    "mains_voltage": {
        "address": 120, "count": 16,
        "fields": {
            "mains_uab":  lambda regs: (regs[1] * 65536 + regs[0]) * 0.1,
            "mains_ubc":  lambda regs: (regs[3] * 65536 + regs[2]) * 0.1,
            "mains_uca":  lambda regs: (regs[5] * 65536 + regs[4]) * 0.1,
            "mains_freq": lambda regs: regs[15] * 0.01,
        },
    },
    "gen_voltage": {
        "address": 140, "count": 19,
        "fields": {
            "gen_uab":    lambda regs: (regs[1] * 65536 + regs[0]) * 0.1,
            "gen_ubc":    lambda regs: (regs[3] * 65536 + regs[2]) * 0.1,
            "gen_uca":    lambda regs: (regs[5] * 65536 + regs[4]) * 0.1,
            "gen_freq":   lambda regs: regs[15] * 0.01,
            "volt_diff":  lambda regs: _signed16(regs[16]) * 0.1,
            "freq_diff":  lambda regs: _signed16(regs[17]) * 0.01,
            "phase_diff": lambda regs: _signed16(regs[18]) * 0.1,
        },
    },
    "power_limit": {
        "address": 159, "count": 4,
        "fields": {
            "current_p_pct": lambda regs: _signed16(regs[0]) * 0.1,
            "target_p_pct":  lambda regs: _signed16(regs[1]) * 0.1,
            "current_q_pct": lambda regs: _signed16(regs[2]) * 0.1,
            "target_q_pct":  lambda regs: _signed16(regs[3]) * 0.1,
        },
    },
    "gen_current": {
        "address": 166, "count": 8,
        "fields": {
            "current_a":     lambda regs: _no_data_or(regs[0], regs[0] * 0.1),
            "current_b":     lambda regs: _no_data_or(regs[1], regs[1] * 0.1),
            "current_c":     lambda regs: _no_data_or(regs[2], regs[2] * 0.1),
            "current_earth": lambda regs: _no_data_or(regs[3], regs[3] * 0.1),
        },
    },
    "power": {
        "address": 174, "count": 28,
        "fields": {
            "power_a":        lambda regs: _signed32(regs[0], regs[1]) * 0.1,
            "power_b":        lambda regs: _signed32(regs[2], regs[3]) * 0.1,
            "power_c":        lambda regs: _signed32(regs[4], regs[5]) * 0.1,
            "power_total":    lambda regs: _signed32(regs[6], regs[7]) * 0.1,
            "reactive_a":     lambda regs: _signed32(regs[8], regs[9]) * 0.1,
            "reactive_b":     lambda regs: _signed32(regs[10], regs[11]) * 0.1,
            "reactive_c":     lambda regs: _signed32(regs[12], regs[13]) * 0.1,
            "reactive_total": lambda regs: _signed32(regs[14], regs[15]) * 0.1,
            "pf_a":           lambda regs: _signed16(regs[24]) * 0.001,
            "pf_b":           lambda regs: _signed16(regs[25]) * 0.001,
            "pf_c":           lambda regs: _signed16(regs[26]) * 0.001,
            "pf_avg":         lambda regs: _signed16(regs[27]) * 0.001,
        },
    },
    "engine": {
        "address": 212, "count": 30,
        "fields": {
            "engine_speed":     lambda regs: None if regs[0] > 5000 or regs[0] == 32766 else regs[0],
            "battery_volt":     lambda regs: _no_data_or(regs[1], regs[1] * 0.1),
            "charger_volt":     lambda regs: _no_data_or(regs[2], regs[2] * 0.1),
            "coolant_temp":     lambda regs: None if _is_bad_temp(regs[8]) else _signed16(regs[8]),
            "oil_pressure":     lambda regs: None if regs[10] >= 10000 or regs[10] == 32766 else regs[10],
            "fuel_level":       lambda regs: None if regs[12] > 100 or regs[12] == 32766 else regs[12],
            "load_pct":         lambda regs: _safe_load(regs[20]),
            "oil_temp":         lambda regs: None if _is_bad_temp(regs[22]) else _signed16(regs[22]),
            "fuel_pressure":    lambda regs: None if regs[24] >= 10000 or regs[24] == 32766 else regs[24],
            "turbo_pressure":   lambda regs: None if regs[28] >= 10000 or regs[28] == 32766 else regs[28],
            "fuel_consumption": lambda regs: None if regs[29] > 10000 or regs[29] == 32766 else regs[29] * 0.1,
        },
    },
    "accumulated": {
        "address": 260, "count": 16,
        "fields": {
            "gen_status":  lambda regs: regs[0],
            "run_hours":   lambda regs: regs[10],
            "run_minutes": lambda regs: regs[11],
            "start_count": lambda regs: regs[13],
            "energy_kwh":  lambda regs: regs[15] * 65536 + regs[14],
        },
    },
    "alarms": {
        "address": 511, "count": 1,
        "fields": {
            "alarm_count": lambda regs: regs[0],
        },
    },
    # Alarm detail split into 5 groups (15 regs each) for RS485 reliability
    "alarm_sd": {
        "address": 1, "count": 15,
        "fields": {
            "alarm_sd_0": lambda regs: regs[0],
            "alarm_sd_1": lambda regs: regs[1],
            "alarm_sd_2": lambda regs: regs[2],
            "alarm_sd_3": lambda regs: regs[3],
            "alarm_sd_4": lambda regs: regs[4],
            "alarm_sd_5": lambda regs: regs[5],
        },
    },
    "alarm_ts": {
        "address": 16, "count": 15,
        "fields": {
            "alarm_ts_0": lambda regs: regs[0],
            "alarm_ts_1": lambda regs: regs[1],
            "alarm_ts_2": lambda regs: regs[2],
            "alarm_ts_3": lambda regs: regs[3],
            "alarm_ts_4": lambda regs: regs[4],
            "alarm_ts_5": lambda regs: regs[5],
        },
    },
    "alarm_tr": {
        "address": 31, "count": 15,
        "fields": {
            "alarm_tr_0": lambda regs: regs[0],
            "alarm_tr_1": lambda regs: regs[1],
            "alarm_tr_2": lambda regs: regs[2],
            "alarm_tr_3": lambda regs: regs[3],
            "alarm_tr_4": lambda regs: regs[4],
            "alarm_tr_5": lambda regs: regs[5],
        },
    },
    "alarm_bk": {
        "address": 76, "count": 15,
        "fields": {
            "alarm_bk_0": lambda regs: regs[0],
            "alarm_bk_1": lambda regs: regs[1],
            "alarm_bk_2": lambda regs: regs[2],
            "alarm_bk_3": lambda regs: regs[3],
            "alarm_bk_4": lambda regs: regs[4],
            "alarm_bk_5": lambda regs: regs[5],
        },
    },
    "alarm_wn": {
        "address": 91, "count": 15,
        "fields": {
            "alarm_wn_0": lambda regs: regs[0],
            "alarm_wn_1": lambda regs: regs[1],
            "alarm_wn_2": lambda regs: regs[2],
            "alarm_wn_3": lambda regs: regs[3],
            "alarm_wn_4": lambda regs: regs[4],
            "alarm_wn_5": lambda regs: regs[5],
        },
    },
}

GEN_STATUS_CODES = {
    0: "standby", 1: "preheat", 2: "fuel_on", 3: "cranking",
    4: "crank_rest", 5: "safety_run", 6: "idle", 7: "warming",
    8: "wait_load", 9: "running", 10: "cooling", 11: "idle_stop",
    12: "ets", 13: "wait_stop", 14: "post_stop", 15: "stop_failure",
}

REGISTER_MAP_9560: dict[str, dict] = {
    "status": {
        "address": 0, "count": 3,
        "fields": {
            "mode_test":       lambda regs: bool(regs[0] & (1 << 8)),
            "mode_auto":       lambda regs: bool(regs[0] & (1 << 9)),
            "mode_manual":     lambda regs: bool(regs[0] & (1 << 10)),
            "mode_stop":       lambda regs: bool(regs[0] & (1 << 11)),
            "alarm_common":    lambda regs: bool(regs[0] & (1 << 0)),
            "alarm_shutdown":  lambda regs: bool(regs[0] & (1 << 1)),
            "alarm_warning":   lambda regs: bool(regs[0] & (1 << 2)),
            "alarm_trip_stop": lambda regs: bool(regs[0] & (1 << 3)),
        },
    },
    "genset_status": {
        "address": 40, "count": 3,
        "fields": {
            "genset_status": lambda regs: regs[0],
        },
    },
    "indicators": {
        "address": 43, "count": 1,
        "fields": {
            "indicators": lambda regs: regs[0],
        },
    },
    "mains_voltage": {
        "address": 55, "count": 10,
        "fields": {
            "mains_uab":  lambda regs: regs[0],
            "mains_ubc":  lambda regs: regs[1],
            "mains_uca":  lambda regs: regs[2],
            "mains_ua":   lambda regs: regs[3],
            "mains_ub":   lambda regs: regs[4],
            "mains_uc":   lambda regs: regs[5],
            "mains_freq": lambda regs: regs[9] * 0.01,
        },
    },
    "busbar_voltage": {
        "address": 75, "count": 10,
        "fields": {
            "busbar_uab":  lambda regs: regs[0],
            "busbar_ubc":  lambda regs: regs[1],
            "busbar_uca":  lambda regs: regs[2],
            "busbar_ua":   lambda regs: regs[3],
            "busbar_ub":   lambda regs: regs[4],
            "busbar_uc":   lambda regs: regs[5],
            "busbar_freq": lambda regs: regs[9] * 0.01,
        },
    },
    "mains_current": {
        "address": 95, "count": 3,
        "fields": {
            "mains_ia": lambda regs: regs[0] * 0.1,
            "mains_ib": lambda regs: regs[1] * 0.1,
            "mains_ic": lambda regs: regs[2] * 0.1,
        },
    },
    "mains_power": {
        "address": 103, "count": 16,
        "fields": {
            "mains_p_a":    lambda regs: _signed32(regs[0], regs[1]) * 0.1,
            "mains_p_b":    lambda regs: _signed32(regs[2], regs[3]) * 0.1,
            "mains_p_c":    lambda regs: _signed32(regs[4], regs[5]) * 0.1,
            "mains_total_p": lambda regs: _signed32(regs[6], regs[7]) * 0.1,
            "mains_q_a":    lambda regs: _signed32(regs[8], regs[9]) * 0.1,
            "mains_q_b":    lambda regs: _signed32(regs[10], regs[11]) * 0.1,
            "mains_q_c":    lambda regs: _signed32(regs[12], regs[13]) * 0.1,
            "mains_total_q": lambda regs: _signed32(regs[14], regs[15]) * 0.1,
        },
    },
    "mains_pf": {
        "address": 127, "count": 4,
        "fields": {
            "mains_pf_a":   lambda regs: _signed16(regs[0]) * 0.01,
            "mains_pf_b":   lambda regs: _signed16(regs[1]) * 0.01,
            "mains_pf_c":   lambda regs: _signed16(regs[2]) * 0.01,
            "mains_pf_avg": lambda regs: _signed16(regs[3]) * 0.01,
        },
    },
    "busbar_misc": {
        "address": 134, "count": 12,
        "fields": {
            "busbar_current": lambda regs: regs[0] * 0.1,
            "battery_volt":   lambda regs: regs[8] * 0.1,
        },
    },
    "busbar_power": {
        "address": 182, "count": 17,
        "fields": {
            "busbar_p":      lambda regs: _signed32(regs[0], regs[1]) * 0.1,
            "busbar_q":      lambda regs: _signed32(regs[2], regs[3]) * 0.1,
            "busbar_switch": lambda regs: regs[11],
            "mains_status":  lambda regs: regs[13],
            "mains_switch":  lambda regs: regs[15],
        },
    },
    "accumulated": {
        "address": 203, "count": 9,
        "fields": {
            "accum_kwh":   lambda regs: _signed32(regs[0], regs[1]) * 0.1,
            "accum_kvarh": lambda regs: _signed32(regs[2], regs[3]) * 0.1,
            "maint_hours": lambda regs: regs[8],
        },
    },
    "running": {
        "address": 270, "count": 4,
        "fields": {
            "running_hours_a":   lambda regs: regs[0],
            "running_minutes_a": lambda regs: regs[1],
            "running_seconds_a": lambda regs: regs[2],
            "start_times_a":     lambda regs: regs[3],
        },
    },
    # Detailed alarm registers — split into smaller reads for RS485 reliability
    "alarm_detail_a": {
        "address": 0, "count": 25,
        "fields": {
            "alarm_reg_00": lambda regs: regs[0],   # Common flags + modes
            "alarm_reg_01": lambda regs: regs[1],   # Shutdown alarms
            "alarm_reg_02": lambda regs: regs[2],   # Shutdown cont.
            "alarm_reg_08": lambda regs: regs[8],   # Input Shutdown 1-8
            "alarm_reg_12": lambda regs: regs[12],  # Trip & Stop
            "alarm_reg_14": lambda regs: regs[14],  # Trip & Stop cont.
            "alarm_reg_16": lambda regs: regs[16],  # Trip
            "alarm_reg_20": lambda regs: regs[20],  # Warning
            "alarm_reg_21": lambda regs: regs[21],  # Warning cont.
            "alarm_reg_24": lambda regs: regs[24],  # Indication
            # Power Limit status bit from reg 21
            "power_limit_active": lambda regs: bool(regs[21] & (1 << 15)),
        },
    },
    "alarm_detail_b": {
        "address": 30, "count": 15,
        "fields": {
            "alarm_reg_30": lambda regs: regs[0],   # Mains Trip
            "alarm_reg_44": lambda regs: regs[14],  # Mains fault detail
            # Power Limit trip bit from reg 30
            "power_limit_trip": lambda regs: bool(regs[0] & (1 << 10)),
        },
    },
}

GENSET_STATUS_9560 = {
    0: "standby", 1: "preheat", 2: "fuel_output", 3: "crank",
    4: "crank_rest", 5: "safety_run", 6: "start_idle",
    7: "warming_up", 8: "wait_load", 9: "running",
    10: "cooling", 11: "stop_idle", 12: "ets",
    13: "wait_stop", 14: "stop_failure",
}

SWITCH_STATUS = {
    0: "synchronizing", 1: "close_delay", 2: "wait_closing",
    3: "closed", 4: "unloading", 5: "open_delay",
    6: "wait_opening", 7: "opened",
}

MAINS_STATUS = {
    0: "normal", 1: "normal_delay", 2: "abnormal", 3: "abnormal_delay",
}


# ---------------------------------------------------------------------------
# Base Reader
# ---------------------------------------------------------------------------

class BaseReader(ABC):
    LOCK_TIMEOUT = 10.0  # max seconds to wait for lock from API calls

    def __init__(self, device: Device, *, site_code: str = ""):
        self.device = device
        self.device_id = device.id
        self.ip = device.ip_address
        self.port = device.port
        self.slave_id = device.slave_id
        self.site_code = site_code
        # Per-device timeouts (fallback to global settings)
        self.timeout = device.modbus_timeout or settings.MODBUS_TIMEOUT
        self.retry_delay = device.retry_delay or settings.MODBUS_RETRY_DELAY
        # Per-device lock: serialises poll-cycle vs API commands
        self._lock = asyncio.Lock()

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def read_all(self) -> dict: ...

    @abstractmethod
    async def write_coil(self, address: int, value: bool) -> None: ...

    @abstractmethod
    async def write_register(self, address: int, value: int) -> None: ...

    @abstractmethod
    async def read_registers(self, address: int, count: int) -> list[int]: ...

    @abstractmethod
    async def _read_registers_unlocked(self, address: int, count: int) -> list[int]:
        """Internal: read registers without acquiring the lock."""
        ...

    async def _write_register_unlocked(self, address: int, value: int) -> None:
        """Internal: write single register without acquiring the lock.

        Override in subclass for protocol-specific implementation.
        Default: delegates to write_register (which acquires lock — be careful).
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement _write_register_unlocked"
        )

    async def read_registers_batch(self, requests: list[tuple[int, int]]) -> list[list[int]]:
        """Read multiple register ranges atomically under one lock acquisition."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError(
                f"Device {self.device_id}: lock timeout ({self.LOCK_TIMEOUT:.0f}s) on batch read"
                f" — poll cycle may be in progress, try again shortly"
            )
        try:
            results = []
            for address, count in requests:
                results.append(await self._read_registers_unlocked(address, count))
            return results
        finally:
            self._lock.release()

    async def write_registers_batch(
        self,
        requests: list[tuple[int, int]],
        *,
        unlock_register: int | None = None,
        unlock_value: int | None = None,
    ) -> list[int] | None:
        """Write multiple registers atomically under one lock.

        Optionally writes an unlock register first (e.g. password).
        After all writes, reads back all values to verify.
        Returns list of read-back values, or None if verify skipped.
        """
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError(
                f"Device {self.device_id}: lock timeout ({self.LOCK_TIMEOUT:.0f}s) on batch write"
                f" — poll cycle may be in progress, try again shortly"
            )
        try:
            # Optional unlock (password) before config writes
            if unlock_register is not None and unlock_value is not None:
                await self._write_register_unlocked(unlock_register, unlock_value)
                await asyncio.sleep(0.1)

            # Write all registers
            for address, value in requests:
                await self._write_register_unlocked(address, value)
                await asyncio.sleep(0.05)  # Small inter-write delay

            # Verify: read back all written registers
            await asyncio.sleep(0.3)

            verify_results = []
            mismatches = []
            for address, value in requests:
                regs = await self._read_registers_unlocked(address, 1)
                read_back = regs[0]
                verify_results.append(read_back)
                if read_back != (value & 0xFFFF):
                    mismatches.append(
                        f"0x{address:04X}: wrote={value} read={read_back}"
                    )

            if mismatches:
                logger.warning(
                    "Batch write verify mismatches device=%s: %s",
                    self.device_id, "; ".join(mismatches),
                )

            return verify_results
        finally:
            self._lock.release()


# ---------------------------------------------------------------------------
# HGM9520N Reader — Modbus TCP (pymodbus)
# ---------------------------------------------------------------------------

class HGM9520NReader(BaseReader):
    """Modbus TCP via pymodbus AsyncModbusTcpClient."""

    RECONNECT_EVERY = 30  # force reconnect every N poll cycles (~60s at POLL_INTERVAL=2)

    def __init__(self, device: Device, *, site_code: str = ""):
        super().__init__(device, site_code=site_code)
        self._client: AsyncModbusTcpClient | None = None
        self._poll_count = 0

    async def connect(self) -> None:
        self._client = AsyncModbusTcpClient(
            host=self.ip,
            port=self.port,
            timeout=self.timeout,
        )
        connected = await self._client.connect()
        if not connected:
            raise ConnectionError(
                f"HGM9520N: cannot connect to {self.ip}:{self.port}"
            )
        logger.info("HGM9520N connected: %s:%s slave=%s timeout=%.1fs", self.ip, self.port, self.slave_id, self.timeout)

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    async def read_all(self) -> dict:
        async with self._lock:
            self._poll_count += 1

            if self._poll_count >= self.RECONNECT_EVERY:
                self._poll_count = 0
                await self.disconnect()

            if not self._client or not self._client.connected:
                await self.connect()

            result: dict = {}
            errors = 0
            total_blocks = len(REGISTER_MAP_9520N)

            for block_name, block in REGISTER_MAP_9520N.items():
                try:
                    resp = await asyncio.wait_for(
                        self._client.read_holding_registers(
                            address=block["address"],
                            count=block["count"],
                            slave=self.slave_id,
                        ),
                        timeout=self.timeout,
                    )
                except (asyncio.TimeoutError, Exception) as exc:
                    logger.warning(
                        "HGM9520N timeout block=%s device=%s: %s",
                        block_name, self.device_id, exc,
                    )
                    errors += 1
                    continue

                if resp.isError():
                    logger.warning(
                        "HGM9520N read error block=%s device=%s: %s",
                        block_name, self.device_id, resp,
                    )
                    errors += 1
                    continue
                regs = list(resp.registers)
                for field_name, parser in block["fields"].items():
                    try:
                        result[field_name] = parser(regs)
                    except Exception as exc:
                        logger.debug("Parse error %s.%s: %s", block_name, field_name, exc)
                        result[field_name] = None

            if errors == total_blocks:
                await self.disconnect()
                raise ConnectionError(f"HGM9520N device={self.device_id}: all {total_blocks} blocks failed")

            if errors > total_blocks // 2:
                logger.warning("HGM9520N device=%s: %d/%d blocks failed, data may be unreliable",
                               self.device_id, errors, total_blocks)

            if "gen_status" in result:
                code = result["gen_status"]
                result["gen_status_text"] = GEN_STATUS_CODES.get(code, f"unknown_{code}")

            return result

    async def write_coil(self, address: int, value: bool) -> None:
        """FC05 — Write Single Coil via pymodbus."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Device {self.device_id}: lock timeout on FC05")
        try:
            if not self._client or not self._client.connected:
                await self.connect()
            resp = await asyncio.wait_for(
                self._client.write_coil(address=address, value=value, slave=self.slave_id),
                timeout=self.timeout,
            )
            if resp.isError():
                raise ConnectionError(f"FC05 error: {resp}")
            logger.info("FC05 OK: device=%s addr=0x%04X value=%s", self.device_id, address, value)
        finally:
            self._lock.release()

    async def write_register(self, address: int, value: int) -> None:
        """FC06 — Write Single Register via pymodbus."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Device {self.device_id}: lock timeout on FC06")
        try:
            if not self._client or not self._client.connected:
                await self.connect()
            resp = await asyncio.wait_for(
                self._client.write_register(address=address, value=value, slave=self.slave_id),
                timeout=self.timeout,
            )
            if resp.isError():
                raise ConnectionError(f"FC06 error: {resp}")
            logger.info("FC06 OK: device=%s addr=0x%04X value=%d", self.device_id, address, value)
        finally:
            self._lock.release()

    async def read_registers(self, address: int, count: int) -> list[int]:
        """FC03 — Read Holding Registers via pymodbus."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Device {self.device_id}: lock timeout on FC03")
        try:
            return await self._read_registers_unlocked(address, count)
        finally:
            self._lock.release()

    async def _read_registers_unlocked(self, address: int, count: int) -> list[int]:
        """FC03 inner logic — no lock, called from locked context."""
        if not self._client or not self._client.connected:
            await self.connect()
        resp = await asyncio.wait_for(
            self._client.read_holding_registers(address=address, count=count, slave=self.slave_id),
            timeout=self.timeout,
        )
        if resp.isError():
            raise ConnectionError(f"FC03 error: {resp}")
        return list(resp.registers)

    async def _write_register_unlocked(self, address: int, value: int) -> None:
        """FC06 inner logic — no lock, called from locked context (e.g. write_registers_batch)."""
        if not self._client or not self._client.connected:
            await self.connect()
        resp = await asyncio.wait_for(
            self._client.write_register(address=address, value=value, slave=self.slave_id),
            timeout=self.timeout,
        )
        if resp.isError():
            raise ConnectionError(f"FC06 error: {resp}")
        logger.info("FC06 OK (unlocked): device=%s addr=0x%04X value=%d", self.device_id, address, value)


# ---------------------------------------------------------------------------
# HGM9560 Reader — RTU over TCP (raw socket + CRC16)
# ---------------------------------------------------------------------------

class HGM9560Reader(BaseReader):
    """Modbus RTU over TCP via raw asyncio socket."""

    INTER_FRAME_DELAY = 0.40   # wait after sending before reading response
    INTER_BLOCK_DELAY = 0.35   # pause between block reads
    PRE_FLUSH_TIMEOUT = 0.25   # how long to wait for silence before sending
    MAX_RETRIES = 2            # retry each block up to 2 times on failure
    # RTU polling cycle holds lock for ~15-30s (15 blocks × ~1-2s each).
    # API calls (spr-config read/write) must wait for the full cycle.
    LOCK_TIMEOUT = 35.0        # override BaseReader's 10s — enough for full poll cycle

    def __init__(self, device: Device, *, site_code: str = ""):
        super().__init__(device, site_code=site_code)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        # RS485 converter needs longer timeout than Modbus TCP
        if self.timeout < 3.0:
            self.timeout = 3.0

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.ip, self.port),
            timeout=self.timeout,
        )
        logger.info("HGM9560 connected: %s:%s slave=%s timeout=%.1fs", self.ip, self.port, self.slave_id, self.timeout)

    async def disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def _flush_stale(self, timeout: float = 0.15) -> int:
        """Drain ALL stale bytes from the buffer in a loop.

        The RS485-to-TCP converter may deliver late responses as multiple
        TCP segments.  We keep reading until the buffer is silent for
        *timeout* seconds.  Returns total bytes flushed.
        """
        if self._reader is None:
            return 0
        total = 0
        while True:
            try:
                chunk = await asyncio.wait_for(self._reader.read(4096), timeout=timeout)
                if chunk:
                    total += len(chunk)
                    continue  # more data may follow
                else:
                    # EOF — peer closed
                    logger.warning("HGM9560: EOF on flush, reconnecting")
                    await self.disconnect()
                    await self.connect()
                    return total
            except asyncio.TimeoutError:
                break
        if total:
            logger.debug("HGM9560: flushed %d stale bytes total", total)
        return total

    async def _send_and_receive(self, start: int, count: int) -> list[int] | None:
        if self._writer is None or self._reader is None:
            raise ConnectionError("HGM9560: not connected")

        # Aggressively flush until silence — ensures no stale data from previous request
        await self._flush_stale(timeout=self.PRE_FLUSH_TIMEOUT)

        frame = build_read_registers(self.slave_id, start, count)
        expected_bytes = 3 + count * 2 + 2  # slave + fc + bytecount + data + crc

        self._writer.write(frame)
        await self._writer.drain()

        # Wait for device to process request + RS485 turnaround + converter delay
        await asyncio.sleep(self.INTER_FRAME_DELAY)

        response = b""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.timeout

        while loop.time() < deadline:
            remaining_time = deadline - loop.time()
            if remaining_time <= 0:
                break
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(512),
                    timeout=min(remaining_time, 0.8),
                )
                if not chunk:
                    raise ConnectionError("HGM9560: connection closed by peer")
                response += chunk

                # Try to find a valid frame starting with our slave_id
                frame_data = self._extract_frame(response, count)
                if frame_data is not None:
                    return parse_read_registers_response(frame_data)

            except asyncio.TimeoutError:
                if response:
                    break
                return None

        # Last attempt: maybe we have enough data but need to search for frame
        if response:
            frame_data = self._extract_frame(response, count)
            if frame_data is not None:
                return parse_read_registers_response(frame_data)

            logger.warning(
                "HGM9560 bad response for block @%d: got %d bytes: %s",
                start, len(response), response[:32].hex(),
            )
        else:
            logger.warning(
                "HGM9560 no response for block @%d", start,
            )
        return None

    def _extract_frame(self, data: bytes, expected_count: int) -> bytes | None:
        """Search for a valid Modbus RTU response frame in the byte buffer.

        The converter may prepend stale bytes from a previous response.
        We scan for our slave_id + FC03 + correct byte-count, then verify CRC.
        """
        expected_data_bytes = expected_count * 2
        frame_len = 3 + expected_data_bytes + 2  # slave + fc + bytecount + data + crc

        for offset in range(len(data) - 4):  # need at least 5 bytes
            if data[offset] != self.slave_id:
                continue
            if data[offset + 1] != 0x03:
                # Check for exception response (FC | 0x80)
                if data[offset + 1] == 0x83 and offset + 5 <= len(data):
                    return data[offset:offset + 5]
                continue
            if data[offset + 2] != expected_data_bytes:
                continue
            # Found candidate: slave=ours, fc=0x03, bytecount matches
            if offset + frame_len > len(data):
                return None  # not enough data yet — keep reading
            candidate = data[offset:offset + frame_len]
            # Verify CRC
            crc_calc = crc16_modbus(candidate[:-2])
            crc_recv = candidate[-2] | (candidate[-1] << 8)
            if crc_calc == crc_recv:
                if offset > 0:
                    logger.debug(
                        "HGM9560: skipped %d garbage bytes before valid frame", offset,
                    )
                return candidate
        return None

    async def read_all(self) -> dict:
        async with self._lock:
            if self._writer is None or self._reader is None:
                await self.connect()

            result: dict = {}
            errors = 0
            total_blocks = len(REGISTER_MAP_9560)
            first_block = True

            for block_name, block in REGISTER_MAP_9560.items():
                if not first_block:
                    await asyncio.sleep(self.INTER_BLOCK_DELAY)
                first_block = False

                regs = None
                for attempt in range(1, self.MAX_RETRIES + 1):
                    try:
                        regs = await self._send_and_receive(block["address"], block["count"])
                    except ConnectionError:
                        break  # connection lost — skip retries

                    if regs is not None:
                        break  # success

                    # Failed — wait for late response to arrive, flush everything, retry
                    if attempt < self.MAX_RETRIES:
                        logger.debug(
                            "HGM9560 block=%s attempt %d/%d failed, retrying",
                            block_name, attempt, self.MAX_RETRIES,
                        )
                        await asyncio.sleep(1.0)
                        await self._flush_stale(timeout=0.3)

                if regs is None:
                    logger.warning(
                        "HGM9560 read error block=%s device=%s (after %d attempts)",
                        block_name, self.device_id, self.MAX_RETRIES,
                    )
                    errors += 1
                    # Aggressive flush before next block — wait for all late data
                    await asyncio.sleep(1.0)
                    await self._flush_stale(timeout=0.3)
                    continue

                for field_name, parser in block["fields"].items():
                    try:
                        result[field_name] = parser(regs)
                    except Exception as exc:
                        logger.debug("Parse error %s.%s: %s", block_name, field_name, exc)
                        result[field_name] = None

            if errors == total_blocks:
                await self.disconnect()
                raise ConnectionError(
                    f"HGM9560 device={self.device_id}: all {total_blocks} blocks failed"
                )

            if errors > total_blocks // 2:
                logger.warning(
                    "HGM9560 device=%s: %d/%d blocks failed, data may be unreliable",
                    self.device_id, errors, total_blocks,
                )

            if "genset_status" in result:
                code = result["genset_status"]
                result["genset_status_text"] = GENSET_STATUS_9560.get(code, f"unknown_{code}")
            if "busbar_switch" in result:
                result["busbar_switch_text"] = SWITCH_STATUS.get(result["busbar_switch"], "unknown")
            if "mains_status" in result:
                result["mains_status_text"] = MAINS_STATUS.get(result["mains_status"], "unknown")
            if "mains_switch" in result:
                result["mains_switch_text"] = SWITCH_STATUS.get(result["mains_switch"], "unknown")

            return result

    async def write_coil(self, address: int, value: bool) -> None:
        """FC05 — Write Single Coil via raw RTU frame."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Device {self.device_id}: lock timeout on FC05")
        try:
            if self._writer is None or self._reader is None:
                await self.connect()

            await self._flush_stale()

            frame = build_write_coil(self.slave_id, address, value)

            self._writer.write(frame)
            await self._writer.drain()

            await asyncio.sleep(self.INTER_FRAME_DELAY)

            # Read echo response (8 bytes)
            try:
                response = await asyncio.wait_for(self._reader.read(256), timeout=self.timeout)
            except asyncio.TimeoutError:
                raise ConnectionError("FC05 timeout: no response from HGM9560")

            _validate_write_echo(frame, response, "FC05")

            logger.info("FC05 OK: device=%s addr=0x%04X value=%s", self.device_id, address, value)
        finally:
            self._lock.release()

    async def write_register(self, address: int, value: int) -> None:
        """FC06 — Write Single Register via raw RTU frame with echo validation."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Device {self.device_id}: lock timeout on FC06")
        try:
            await self._write_register_unlocked(address, value)
        finally:
            self._lock.release()

    async def _write_register_unlocked(self, address: int, value: int) -> None:
        """FC06 inner logic — no lock, called from locked context."""
        if self._writer is None or self._reader is None:
            await self.connect()

        await self._flush_stale()

        frame = build_write_register(self.slave_id, address, value)

        logger.info(
            "FC06 SEND: device=%s addr=0x%04X value=%d frame=%s",
            self.device_id, address, value, frame.hex(),
        )

        self._writer.write(frame)
        await self._writer.drain()

        await asyncio.sleep(self.INTER_FRAME_DELAY)

        # Read echo response (8 bytes)
        try:
            response = await asyncio.wait_for(self._reader.read(256), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise ConnectionError("FC06 timeout: no response from HGM9560")

        logger.info(
            "FC06 RECV: device=%s response=%s (%d bytes)",
            self.device_id, response.hex(), len(response),
        )

        _validate_write_echo(frame, response, "FC06")

        logger.info(
            "FC06 OK: device=%s addr=0x%04X value=%d",
            self.device_id, address, value,
        )

    async def read_registers(self, address: int, count: int) -> list[int]:
        """FC03 — Read Holding Registers via raw RTU frame."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Device {self.device_id}: lock timeout on FC03")
        try:
            return await self._read_registers_unlocked(address, count)
        finally:
            self._lock.release()

    async def _read_registers_unlocked(self, address: int, count: int) -> list[int]:
        """FC03 inner logic — no lock, called from locked context."""
        if self._writer is None or self._reader is None:
            await self.connect()
        regs = await self._send_and_receive(address, count)
        if regs is None:
            raise ConnectionError(f"FC03 read failed: addr=0x{address:04X} count={count}")
        return regs


# ---------------------------------------------------------------------------
# HGM9520N RTU Reader — HGM9520N register map over RTU-over-TCP transport
# ---------------------------------------------------------------------------

class HGM9520NRtuReader(HGM9560Reader):
    """HGM9520N via RTU-over-TCP (raw asyncio socket + CRC16).

    Reuses the full RTU transport from HGM9560Reader (connect, flush,
    send_and_receive, frame extraction, FC05/FC06/FC03) but reads
    HGM9520N register map and uses HGM9520N status codes.
    """

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.ip, self.port),
            timeout=self.timeout,
        )
        logger.info(
            "HGM9520N-RTU connected: %s:%s slave=%s timeout=%.1fs",
            self.ip, self.port, self.slave_id, self.timeout,
        )

    async def read_all(self) -> dict:
        async with self._lock:
            if self._writer is None or self._reader is None:
                await self.connect()

            result: dict = {}
            errors = 0
            total_blocks = len(REGISTER_MAP_9520N_RTU)
            first_block = True

            for block_name, block in REGISTER_MAP_9520N_RTU.items():
                if not first_block:
                    await asyncio.sleep(self.INTER_BLOCK_DELAY)
                first_block = False

                regs = None
                for attempt in range(1, self.MAX_RETRIES + 1):
                    try:
                        regs = await self._send_and_receive(
                            block["address"], block["count"],
                        )
                    except ConnectionError:
                        break  # connection lost — skip retries

                    if regs is not None:
                        break  # success

                    # Failed — wait, flush, retry
                    if attempt < self.MAX_RETRIES:
                        logger.debug(
                            "HGM9520N-RTU block=%s attempt %d/%d failed, retrying",
                            block_name, attempt, self.MAX_RETRIES,
                        )
                        await asyncio.sleep(1.0)
                        await self._flush_stale(timeout=0.3)

                if regs is None:
                    logger.warning(
                        "HGM9520N-RTU read error block=%s device=%s (after %d attempts)",
                        block_name, self.device_id, self.MAX_RETRIES,
                    )
                    errors += 1
                    # Aggressive flush before next block
                    await asyncio.sleep(1.0)
                    await self._flush_stale(timeout=0.3)
                    continue

                for field_name, parser in block["fields"].items():
                    try:
                        result[field_name] = parser(regs)
                    except Exception as exc:
                        logger.debug(
                            "Parse error %s.%s: %s", block_name, field_name, exc,
                        )
                        result[field_name] = None

            if errors == total_blocks:
                await self.disconnect()
                raise ConnectionError(
                    f"HGM9520N-RTU device={self.device_id}: "
                    f"all {total_blocks} blocks failed"
                )

            if errors > total_blocks // 2:
                logger.warning(
                    "HGM9520N-RTU device=%s: %d/%d blocks failed, data may be unreliable",
                    self.device_id, errors, total_blocks,
                )

            # HGM9520N status postprocessing (same as HGM9520NReader)
            if "gen_status" in result:
                code = result["gen_status"]
                result["gen_status_text"] = GEN_STATUS_CODES.get(
                    code, f"unknown_{code}",
                )

            return result


# ---------------------------------------------------------------------------
# ModbusPoller — main polling orchestrator
# ---------------------------------------------------------------------------

def _make_reader(device: Device, *, site_code: str = "") -> BaseReader:
    from models.device import DeviceType

    if device.device_type == DeviceType.GENERATOR:
        if device.protocol == ModbusProtocol.RTU_OVER_TCP:
            return HGM9520NRtuReader(device, site_code=site_code)
        return HGM9520NReader(device, site_code=site_code)
    else:  # ATS (HGM9560)
        return HGM9560Reader(device, site_code=site_code)


class ModbusPoller:
    """Background poller: reads devices from DB, polls via Modbus, publishes to Redis."""

    def __init__(self, redis: Redis, session_factory: async_sessionmaker[AsyncSession]):
        self.redis = redis
        self.session_factory = session_factory
        self._running = False
        self._readers: dict[int, BaseReader] = {}
        self._last_poll: dict[int, float] = {}  # device_id -> last poll timestamp
        self._poll_intervals: dict[int, float] = {}  # device_id -> per-device interval

    async def _load_devices(self) -> list[Device]:
        from sqlalchemy.orm import selectinload

        async with self.session_factory() as session:
            stmt = (
                select(Device)
                .where(Device.is_active == True)  # noqa: E712
                .options(selectinload(Device.site))
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _flush_stale_metrics(self) -> None:
        """Delete all device:*:metrics keys from Redis on startup.

        Prevents stale data (e.g. from a previous DemoPoller session)
        from being served via WS snapshot to frontends.
        """
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await self.redis.scan(
                cursor=cursor, match="device:*:metrics", count=100,
            )
            if keys:
                await self.redis.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        if deleted:
            logger.info("Flushed %d stale metric keys from Redis", deleted)

    async def start(self) -> None:
        self._running = True
        logger.info("ModbusPoller starting...")

        # Flush stale metrics from Redis (e.g. leftover from DemoPoller)
        await self._flush_stale_metrics()

        devices = await self._load_devices()
        if not devices:
            logger.warning("No active devices found in DB")

        for dev in devices:
            sc = dev.site.code if dev.site else ""
            self._readers[dev.id] = _make_reader(dev, site_code=sc)
            self._poll_intervals[dev.id] = dev.poll_interval or settings.POLL_INTERVAL
            self._last_poll[dev.id] = 0  # poll immediately on first cycle
            logger.info(
                "Registered reader for device %s (%s) at %s:%s [%s] site=%s interval=%.1fs",
                dev.id, dev.name, dev.ip_address, dev.port, dev.protocol.value, sc,
                self._poll_intervals[dev.id],
            )

        self._reload_requested = False
        self._reload_task = asyncio.create_task(self._listen_reload())

        while self._running:
            if self._reload_requested:
                self._reload_requested = False
                await self.reload_devices()
            await self._poll_cycle()
            # Sleep at minimum interval (1s floor) to avoid busy-loop
            min_interval = min(self._poll_intervals.values()) if self._poll_intervals else settings.POLL_INTERVAL
            await asyncio.sleep(max(1.0, min_interval))

    async def stop(self) -> None:
        logger.info("ModbusPoller stopping...")
        self._running = False
        if hasattr(self, '_reload_task'):
            self._reload_task.cancel()
        for reader in self._readers.values():
            try:
                await reader.disconnect()
            except Exception as exc:
                logger.debug("Disconnect error: %s", exc)
        self._readers.clear()

    async def reload_devices(self) -> None:
        """Hot-reload: re-read devices from DB and recreate readers."""
        logger.info("ModbusPoller: reloading devices from DB...")

        new_devices = await self._load_devices()
        new_device_map = {d.id: d for d in new_devices}

        removed_ids = set(self._readers.keys()) - set(new_device_map.keys())
        for rid in removed_ids:
            logger.info("Removing reader for deleted device %s", rid)
            try:
                await self._readers[rid].disconnect()
            except Exception:
                pass
            del self._readers[rid]
            self._poll_intervals.pop(rid, None)
            self._last_poll.pop(rid, None)
            # Clean up stale Redis key so WS snapshot doesn't send ghost data
            await self.redis.delete(f"device:{rid}:metrics")

        for dev in new_devices:
            sc = dev.site.code if dev.site else ""
            # Always update poll_interval (could change in settings)
            self._poll_intervals[dev.id] = dev.poll_interval or settings.POLL_INTERVAL

            existing_reader = self._readers.get(dev.id)
            if existing_reader:
                # Update per-device timeouts
                existing_reader.timeout = dev.modbus_timeout or settings.MODBUS_TIMEOUT
                existing_reader.retry_delay = dev.retry_delay or settings.MODBUS_RETRY_DELAY

                if (existing_reader.ip != dev.ip_address
                        or existing_reader.port != dev.port
                        or existing_reader.slave_id != dev.slave_id
                        or existing_reader.device.protocol != dev.protocol):
                    logger.info(
                        "Device %s config changed (%s:%s/%s -> %s:%s/%s), reconnecting",
                        dev.id, existing_reader.ip, existing_reader.port,
                        existing_reader.device.protocol.value,
                        dev.ip_address, dev.port, dev.protocol.value,
                    )
                    try:
                        await existing_reader.disconnect()
                    except Exception:
                        pass
                    self._readers[dev.id] = _make_reader(dev, site_code=sc)
                else:
                    # Update cached site_code even if connection params didn't change
                    existing_reader.site_code = sc
            else:
                logger.info(
                    "New device %s (%s) at %s:%s [%s]",
                    dev.id, dev.name, dev.ip_address, dev.port, dev.protocol.value,
                )
                self._readers[dev.id] = _make_reader(dev, site_code=sc)
                self._last_poll[dev.id] = 0  # poll immediately

        logger.info("ModbusPoller: reload complete. Active readers: %d", len(self._readers))

    async def _listen_reload(self) -> None:
        """Listen to Redis channel poller:reload for hot-reload signals."""
        while self._running:
            pubsub = self.redis.pubsub()
            try:
                await pubsub.subscribe("poller:reload")
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        logger.info("Received reload signal")
                        self._reload_requested = True
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Reload listener error: %s, reconnecting in 2s", exc)
                await asyncio.sleep(2)
            finally:
                try:
                    await pubsub.unsubscribe("poller:reload")
                    await pubsub.close()
                except Exception:
                    pass

    async def _poll_cycle(self) -> None:
        now = _time.monotonic()
        tasks = []
        for device_id, reader in self._readers.items():
            interval = self._poll_intervals.get(device_id, settings.POLL_INTERVAL)
            last = self._last_poll.get(device_id, 0)
            if now - last >= interval:
                self._last_poll[device_id] = now
                tasks.append(self._poll_device(device_id, reader))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll_device(self, device_id: int, reader: BaseReader) -> None:
        try:
            data = await reader.read_all()
            if not data:
                logger.warning("Device %s: read_all returned empty data", device_id)
                await self._publish(device_id, reader, {}, online=False, error="no data received")
                await reader.disconnect()
            else:
                await self._publish(device_id, reader, data, online=True)
        except Exception as exc:
            logger.error(
                "Poll error device=%s (%s): %s",
                device_id, reader.ip, exc,
            )
            await self._publish(device_id, reader, {}, online=False, error=str(exc))
            try:
                await reader.disconnect()
            except Exception:
                pass
            await asyncio.sleep(reader.retry_delay)

    async def _publish(
        self,
        device_id: int,
        reader: BaseReader,
        data: dict,
        *,
        online: bool,
        error: str | None = None,
    ) -> None:
        # site_code cached in reader — no DB query on every publish
        payload = {
            "device_id": device_id,
            "site_code": reader.site_code,
            "device_type": reader.device.device_type.value if reader.device.device_type else "unknown",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "online": online,
            "error": error,
            **data,
        }

        json_str = json.dumps(payload, default=str)
        redis_key = f"device:{device_id}:metrics"

        # TTL 30s — stale metrics auto-expire if poller stops
        await self.redis.set(redis_key, json_str, ex=30)
        await self.redis.publish("metrics:updates", json_str)

        if online:
            logger.debug("Published metrics for device %s", device_id)
        else:
            logger.warning("Device %s offline: %s", device_id, error)
