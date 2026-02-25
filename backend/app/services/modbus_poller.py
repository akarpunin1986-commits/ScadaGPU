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
            # Note: regs[13-19] (addresses 225-231) are NOT RTC for HGM9520N —
            # they return sentinel values 65535/32767/0. RTC only available on HGM9560.
        },
    },
    "accumulated": {
        "address": 260, "count": 16,
        "fields": {
            "gen_status":       lambda regs: regs[0],
            "gen_ats_status":   lambda regs: regs[4],   # reg 264: Gen ATS Status
            "mains_ats_status": lambda regs: regs[8],   # reg 268: Mains ATS Status
            "run_hours":        lambda regs: regs[10],
            "run_minutes":      lambda regs: regs[11],
            "start_count":      lambda regs: regs[13],
            "energy_kwh":       lambda regs: regs[15] * 65536 + regs[14],
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
    # gen_voltage(140,19) + power_limit(159,4) merged → addr 140, count 23
    "gen_volt_plimit": {
        "address": 140, "count": 23,
        "fields": {
            # gen_voltage fields (offsets 0-18)
            "gen_uab":    lambda regs: (regs[1] * 65536 + regs[0]) * 0.1,
            "gen_ubc":    lambda regs: (regs[3] * 65536 + regs[2]) * 0.1,
            "gen_uca":    lambda regs: (regs[5] * 65536 + regs[4]) * 0.1,
            "gen_freq":   lambda regs: regs[15] * 0.01,
            "volt_diff":  lambda regs: _signed16(regs[16]) * 0.1,
            "freq_diff":  lambda regs: _signed16(regs[17]) * 0.01,
            "phase_diff": lambda regs: _signed16(regs[18]) * 0.1,
            # power_limit fields (offsets 19-22, were addr 159-162)
            "current_p_pct": lambda regs: _signed16(regs[19]) * 0.1,
            "target_p_pct":  lambda regs: _signed16(regs[20]) * 0.1,
            "current_q_pct": lambda regs: _signed16(regs[21]) * 0.1,
            "target_q_pct":  lambda regs: _signed16(regs[22]) * 0.1,
        },
    },
    # gen_current(166,8) + power(174,28) merged → addr 166, count 36
    "gen_current_power": {
        "address": 166, "count": 36,
        "fields": {
            # gen_current fields (offsets 0-3)
            "current_a":     lambda regs: _no_data_or(regs[0], regs[0] * 0.1),
            "current_b":     lambda regs: _no_data_or(regs[1], regs[1] * 0.1),
            "current_c":     lambda regs: _no_data_or(regs[2], regs[2] * 0.1),
            "current_earth": lambda regs: _no_data_or(regs[3], regs[3] * 0.1),
            # power fields (offsets 8-35, were addr 174-201)
            "power_a":        lambda regs: _signed32(regs[8], regs[9]) * 0.1,
            "power_b":        lambda regs: _signed32(regs[10], regs[11]) * 0.1,
            "power_c":        lambda regs: _signed32(regs[12], regs[13]) * 0.1,
            "power_total":    lambda regs: _signed32(regs[14], regs[15]) * 0.1,
            "reactive_a":     lambda regs: _signed32(regs[16], regs[17]) * 0.1,
            "reactive_b":     lambda regs: _signed32(regs[18], regs[19]) * 0.1,
            "reactive_c":     lambda regs: _signed32(regs[20], regs[21]) * 0.1,
            "reactive_total": lambda regs: _signed32(regs[22], regs[23]) * 0.1,
            "pf_a":           lambda regs: _signed16(regs[32]) * 0.001,
            "pf_b":           lambda regs: _signed16(regs[33]) * 0.001,
            "pf_c":           lambda regs: _signed16(regs[34]) * 0.001,
            "pf_avg":         lambda regs: _signed16(regs[35]) * 0.001,
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
            # Note: regs[13-19] (addresses 225-231) are NOT RTC for HGM9520N —
            # they return sentinel values 65535/32767/0. RTC only available on HGM9560.
        },
    },
    "accumulated": {
        "address": 260, "count": 16,
        "fields": {
            "gen_status":       lambda regs: regs[0],
            "gen_ats_status":   lambda regs: regs[4],   # reg 264: Gen ATS Status
            "mains_ats_status": lambda regs: regs[8],   # reg 268: Mains ATS Status
            "run_hours":        lambda regs: regs[10],
            "run_minutes":      lambda regs: regs[11],
            "start_count":      lambda regs: regs[13],
            "energy_kwh":       lambda regs: regs[15] * 65536 + regs[14],
        },
    },
    "alarms": {
        "address": 511, "count": 1,
        "fields": {
            "alarm_count": lambda regs: regs[0],
        },
    },
    # Alarm detail: original 105-reg block split into 5 × 6-reg reads
    # for reliable transfer over RS485 converters.
    "alarm_sd": {
        "address": 1, "count": 6,
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
        "address": 16, "count": 6,
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
        "address": 31, "count": 6,
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
        "address": 76, "count": 6,
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
        "address": 91, "count": 6,
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
    # genset_status(40,3) + indicators(43,1) merged → addr 40, count 4
    "genset_indicators": {
        "address": 40, "count": 4,
        "fields": {
            "genset_status": lambda regs: regs[0],
            "indicators":    lambda regs: regs[3],  # was addr 43, now offset 3
        },
    },
    # mains_voltage(55,10) + gap(65-74) + busbar_voltage(75,10) → merged
    "mains_busbar_voltage": {
        "address": 55, "count": 30,
        "fields": {
            "mains_uab":  lambda regs: regs[0],       # addr 55
            "mains_ubc":  lambda regs: regs[1],       # addr 56
            "mains_uca":  lambda regs: regs[2],       # addr 57
            "mains_ua":   lambda regs: regs[3],       # addr 58
            "mains_ub":   lambda regs: regs[4],       # addr 59
            "mains_uc":   lambda regs: regs[5],       # addr 60
            "mains_freq": lambda regs: regs[9] * 0.01,  # addr 64
            "busbar_uab":  lambda regs: regs[20],     # addr 75 (offset 75-55=20)
            "busbar_ubc":  lambda regs: regs[21],     # addr 76
            "busbar_uca":  lambda regs: regs[22],     # addr 77
            "busbar_ua":   lambda regs: regs[23],     # addr 78
            "busbar_ub":   lambda regs: regs[24],     # addr 79
            "busbar_uc":   lambda regs: regs[25],     # addr 80
            "busbar_freq": lambda regs: regs[29] * 0.01,  # addr 84 (offset 29)
        },
    },
    # mains_current(95,3) + gap(98-102) + mains_power(103,16) → merged
    "mains_current_power": {
        "address": 95, "count": 24,
        "fields": {
            "mains_ia":      lambda regs: regs[0] * 0.1,   # addr 95
            "mains_ib":      lambda regs: regs[1] * 0.1,   # addr 96
            "mains_ic":      lambda regs: regs[2] * 0.1,   # addr 97
            "mains_p_a":     lambda regs: _signed32(regs[8], regs[9]) * 0.1,    # addr 103 (offset 8)
            "mains_p_b":     lambda regs: _signed32(regs[10], regs[11]) * 0.1,  # addr 105
            "mains_p_c":     lambda regs: _signed32(regs[12], regs[13]) * 0.1,  # addr 107
            "mains_total_p": lambda regs: _signed32(regs[14], regs[15]) * 0.1,  # addr 109
            "mains_q_a":     lambda regs: _signed32(regs[16], regs[17]) * 0.1,  # addr 111
            "mains_q_b":     lambda regs: _signed32(regs[18], regs[19]) * 0.1,  # addr 113
            "mains_q_c":     lambda regs: _signed32(regs[20], regs[21]) * 0.1,  # addr 115
            "mains_total_q": lambda regs: _signed32(regs[22], regs[23]) * 0.1,  # addr 117
        },
    },
    # mains_pf(127,4) + gap(131-133) + busbar_misc(134,12) → merged
    "mains_pf_busbar": {
        "address": 127, "count": 19,
        "fields": {
            "mains_pf_a":     lambda regs: _signed16(regs[0]) * 0.01,  # addr 127
            "mains_pf_b":     lambda regs: _signed16(regs[1]) * 0.01,  # addr 128
            "mains_pf_c":     lambda regs: _signed16(regs[2]) * 0.01,  # addr 129
            "mains_pf_avg":   lambda regs: _signed16(regs[3]) * 0.01,  # addr 130
            "busbar_current": lambda regs: regs[7] * 0.1,    # addr 134 (offset 7)
            "battery_volt":   lambda regs: regs[15] * 0.1,   # addr 142 (offset 15)
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
    # Multi-set Total Active Power — total generator power from MSC communication
    "multiset_power": {
        "address": 235, "count": 2,
        "fields": {
            "multiset_total_p": lambda regs: _signed32(regs[0], regs[1]) * 0.1,
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
    # Controller RTC — registers 225-231 (sec, min, hour, day, month, year, weekday)
    "rtc": {
        "address": 225, "count": 7,
        "fields": {
            "rtc_sec":     lambda regs: regs[0],
            "rtc_min":     lambda regs: regs[1],
            "rtc_hour":    lambda regs: regs[2],
            "rtc_day":     lambda regs: regs[3],
            "rtc_month":   lambda regs: regs[4],
            "rtc_year":    lambda regs: regs[5],
            "rtc_weekday": lambda regs: regs[6],
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

# ATS Status Table (HGM9520N: Gen ATS Status reg 264, Mains ATS Status reg 268)
# Same codes as SWITCH_STATUS but used specifically for generator ATS
ATS_STATUS_CODES = SWITCH_STATUS  # 0=synchronizing ... 3=closed ... 7=opened


# ---------------------------------------------------------------------------
# Adaptive Polling — tiered block sets + standby skip
# ---------------------------------------------------------------------------

_SLOW_POLL_EVERY = 5  # slow block rotation period (each slot read every Nth cycle)

# HGM9520N-RTU: slow blocks spread across slots 1-4 (max 2 per cycle)
# Slot 0 = fast-only cycle (no extra slow blocks)
_9520N_RTU_SLOW_SLOTS: dict[str, int] = {
    "breaker": 1,       "mains_voltage": 1,
    "alarms": 2,        "alarm_sd": 2,
    "alarm_ts": 3,      "alarm_tr": 3,
    "alarm_bk": 4,      "alarm_wn": 4,
}
_9520N_RTU_SLOW_BLOCKS = frozenset(_9520N_RTU_SLOW_SLOTS.keys())
# "accumulated" is FAST — contains gen_status + gen_ats_status (needed every cycle)
# Fast (every cycle): status, accumulated, gen_volt_plimit, gen_current_power, engine

# HGM9560: slow blocks spread across slots 1-4 (max 2 per cycle)
_9560_SLOW_SLOTS: dict[str, int] = {
    "running": 1,        "multiset_power": 1,
    "alarm_detail_a": 2, "alarm_detail_b": 2,
    "rtc": 3,
}
_9560_SLOW_BLOCKS = frozenset(_9560_SLOW_SLOTS.keys())

# Blocks to skip when generator is in standby (gen_status == 0)
_9520N_STANDBY_SKIP = frozenset({
    "gen_volt_plimit", "gen_current_power", "engine", "mains_voltage",
})


# ---------------------------------------------------------------------------
# Opportunistic Sniffing — byte_count → block_name lookup tables
# ---------------------------------------------------------------------------

def _build_bytecount_map(reg_map: dict[str, dict]) -> dict[int, str]:
    """Build mapping from unique byte_count to block_name for sniffer."""
    temp: dict[int, str | None] = {}
    for block_name, block_def in reg_map.items():
        bc = block_def["count"] * 2
        if bc in temp:
            temp[bc] = None  # ambiguous — multiple blocks with same byte_count
        else:
            temp[bc] = block_name
    return {k: v for k, v in temp.items() if v is not None}


_9520N_RTU_BYTECOUNT_MAP = _build_bytecount_map(REGISTER_MAP_9520N_RTU)
# Expected: {46: "gen_volt_plimit", 72: "gen_current_power", 60: "engine", 32: "accumulated"}
# Note: alarm_sd/ts/tr/bk/wn all have count=6 (12 bytes) — ambiguous, excluded from sniffing

_9560_BYTECOUNT_MAP = _build_bytecount_map(REGISTER_MAP_9560)


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
    async def read_all(self, *, skip_bus_wait: bool = False) -> dict: ...

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
            # First write gets full bus-wait + retry; subsequent are quick
            if unlock_register is not None and unlock_value is not None:
                await self._write_register_unlocked(unlock_register, unlock_value, use_retry=True)
                await asyncio.sleep(0.1)

            # Write all registers
            for i, (address, value) in enumerate(requests):
                await self._write_register_unlocked(
                    address, value,
                    use_retry=(i == 0 and unlock_register is None),
                )
                await asyncio.sleep(0.05)  # Small inter-write delay

            # Verify: read back all written registers
            await asyncio.sleep(0.3)

            verify_results = []
            mismatches = []
            for address, value in requests:
                regs = await self._read_registers_unlocked(address, 1, skip_flush=True)
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

    RECONNECT_EVERY = 100  # force reconnect every N poll cycles (~200s at POLL_INTERVAL=2)
    MAX_RETRIES = 2  # retry failed blocks once before giving up

    def __init__(self, device: Device, *, site_code: str = ""):
        super().__init__(device, site_code=site_code)
        self._client: AsyncModbusTcpClient | None = None
        self._poll_count = 0
        self._power_logged = False

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

    async def read_all(self, *, skip_bus_wait: bool = False) -> dict:
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
                regs = None
                for attempt in range(1, self.MAX_RETRIES + 1):
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
                        if attempt < self.MAX_RETRIES:
                            await asyncio.sleep(0.15)
                            continue
                        logger.warning(
                            "HGM9520N timeout block=%s device=%s: %s (attempt %d)",
                            block_name, self.device_id, exc, attempt,
                        )
                        errors += 1
                        break

                    if resp.isError():
                        if attempt < self.MAX_RETRIES:
                            await asyncio.sleep(0.15)
                            continue
                        logger.warning(
                            "HGM9520N read error block=%s device=%s: %s (attempt %d)",
                            block_name, self.device_id, resp, attempt,
                        )
                        errors += 1
                        break
                    regs = list(resp.registers)
                    break
                if regs is None:
                    continue
                for field_name, parser in block["fields"].items():
                    try:
                        result[field_name] = parser(regs)
                    except Exception as exc:
                        logger.debug("Parse error %s.%s: %s", block_name, field_name, exc)
                        result[field_name] = None
                # Log raw power registers once for diagnostics
                if block_name == "power" and not self._power_logged:
                    self._power_logged = True
                    logger.info(
                        "Device %s power RAW regs[174-181]=%s → power_total=%.1f kW",
                        self.device_id, regs[:8], result.get("power_total", 0),
                    )

            if errors == total_blocks:
                await self.disconnect()
                raise ConnectionError(f"HGM9520N device={self.device_id}: all {total_blocks} blocks failed")

            if errors > total_blocks // 2:
                logger.warning("HGM9520N device=%s: %d/%d blocks failed, data may be unreliable",
                               self.device_id, errors, total_blocks)

            if "gen_status" in result:
                code = result["gen_status"]
                result["gen_status_text"] = GEN_STATUS_CODES.get(code, f"unknown_{code}")
            if "gen_ats_status" in result:
                code = result["gen_ats_status"]
                result["gen_ats_status_text"] = ATS_STATUS_CODES.get(code, f"unknown_{code}")
            if "mains_ats_status" in result:
                code = result["mains_ats_status"]
                result["mains_ats_status_text"] = ATS_STATUS_CODES.get(code, f"unknown_{code}")

            # Normalize sync parameters
            if "phase_diff" in result and result["phase_diff"] is not None:
                pd = result["phase_diff"]
                if pd > 180:
                    result["phase_diff"] = pd - 360  # 359.8° → -0.2°
                elif pd < -180:
                    result["phase_diff"] = pd + 360
                # Filter garbage values from stopped generators
                if abs(result["phase_diff"]) > 180:
                    result["phase_diff"] = None

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

# Shared TCP connections for RS485 converters.
# Multiple RTU devices on the same bus (ip:port) must share one TCP socket.
_rtu_connections: dict[str, tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}

# Shared bus-level locks: all readers on the same ip:port MUST use the same lock
# to prevent concurrent read() on a shared StreamReader.
_rtu_bus_locks: dict[str, asyncio.Lock] = {}


def _get_bus_lock(bus_key: str) -> asyncio.Lock:
    """Get or create a shared asyncio.Lock for the given bus (ip:port)."""
    if bus_key not in _rtu_bus_locks:
        _rtu_bus_locks[bus_key] = asyncio.Lock()
    return _rtu_bus_locks[bus_key]


# Opportunistic sniffing: cache frames from other slaves found in the buffer.
# Structure: bus_key → slave_id → byte_count → (timestamp, register_values)
_bus_sniffed: dict[str, dict[int, dict[int, tuple[float, list[int]]]]] = {}
_SNIFF_TTL = 3.0  # seconds — cached sniffed data is valid for this long


class HGM9560Reader(BaseReader):
    """Modbus RTU over TCP via raw asyncio socket."""

    INTER_FRAME_DELAY = 0.03   # wait after sending before reading response
    INTER_BLOCK_DELAY = 0.10   # pause between block reads when switching slaves
    INTER_BLOCK_DELAY_FAST = 0.03  # pause between blocks of the same slave (rapid-fire)
    BUS_SILENCE_REQUIRED = 0.40  # 400ms silence = real MSC quiet window (inter-frame gaps are 170-300ms)
    BUS_LISTEN_MAX = 5.0       # MSC cycle is 4-5s; wait up to one full cycle
    MAX_RETRIES = 2            # retry critical blocks (status, accumulated) up to 2 times
    MAX_RETRIES_FAST = 1       # retry non-critical blocks only once — save time
    LOCK_TIMEOUT = 25.0        # enough for full poll cycle with longer pauses
    FOREIGN_FRAME_CAP = 0.25   # max remaining time after detecting foreign frame
    # Blocks that deserve extra retries (status/mode flags are critical)
    _CRITICAL_BLOCKS = frozenset({"status", "accumulated"})

    def __init__(self, device: Device, *, site_code: str = ""):
        super().__init__(device, site_code=site_code)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        # Override per-device lock with shared bus lock:
        # all RTU readers on the same ip:port share one TCP socket,
        # so they MUST serialize all socket I/O through one lock.
        bus_key = f"{self.ip}:{self.port}"
        self._lock = _get_bus_lock(bus_key)
        # RS485 converter: at 9600 8N1 + packtime=50ms, typical response ~140-230ms
        # 600ms is enough with margin; faster failure = less wasted bus time
        if self.timeout < 0.6:
            self.timeout = 0.6
        # Adaptive polling state
        self._adaptive_poll_count: int = 0
        self._last_result: dict = {}  # cached result from previous cycle

    async def connect(self) -> None:
        bus_key = f"{self.ip}:{self.port}"
        # Reuse shared connection for the same converter
        if bus_key in _rtu_connections:
            r, w = _rtu_connections[bus_key]
            if w and not w.is_closing():
                self._reader, self._writer = r, w
                logger.info(
                    "HGM9560 reusing connection: %s slave=%s timeout=%.1fs",
                    bus_key, self.slave_id, self.timeout,
                )
                return
            else:
                # Stale connection — remove and reconnect
                del _rtu_connections[bus_key]

        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.ip, self.port),
            timeout=self.timeout,
        )
        _rtu_connections[bus_key] = (self._reader, self._writer)
        logger.info("HGM9560 connected: %s slave=%s timeout=%.1fs", bus_key, self.slave_id, self.timeout)

    async def disconnect(self) -> None:
        bus_key = f"{self.ip}:{self.port}"
        if self._writer:
            shared = _rtu_connections.get(bus_key)
            if shared and shared[1] is self._writer:
                # Shared connection — close socket and remove from registry.
                # Other readers on this bus will reconnect on next poll.
                try:
                    self._writer.close()
                    await self._writer.wait_closed()
                except Exception:
                    pass
                _rtu_connections.pop(bus_key, None)
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
        buf = b""
        while True:
            try:
                chunk = await asyncio.wait_for(self._reader.read(4096), timeout=timeout)
                if chunk:
                    total += len(chunk)
                    buf += chunk
                    continue  # more data may follow
                else:
                    # EOF — peer closed
                    logger.warning("HGM9560: EOF on flush, reconnecting")
                    await self.disconnect()
                    await self.connect()
                    return total
            except asyncio.TimeoutError:
                break
        if buf:
            # Parse flushed MSC traffic for sniff cache
            self._sniff_raw_buffer(buf)
            logger.debug("HGM9560: flushed %d stale bytes total", total)
        return total

    async def _wait_bus_silence(self) -> None:
        """Carrier-sense: wait for bus silence before transmitting.

        Listens to the RS485 bus (via TCP converter) until we observe
        BUS_SILENCE_REQUIRED ms of quiet, meaning we're in the MSC gap.
        Any data received is parsed for sniff cache.
        Uses adaptive silence threshold: starts strict (400ms) and
        progressively relaxes after 3s to avoid timing out entirely.
        """
        if self._reader is None:
            return
        loop = asyncio.get_event_loop()
        t_start = loop.time()
        deadline = t_start + self.BUS_LISTEN_MAX
        buf = b""
        while loop.time() < deadline:
            remaining = deadline - loop.time()
            elapsed = loop.time() - t_start
            # Adaptive: relax silence threshold as time passes to avoid
            # timing out entirely (which causes cascade of failures)
            if elapsed < 3.0:
                silence_goal = self.BUS_SILENCE_REQUIRED  # 400ms
            elif elapsed < 4.0:
                silence_goal = 0.30  # 300ms fallback
            else:
                silence_goal = 0.25  # 250ms emergency
            silence_timeout = min(silence_goal, remaining)
            if silence_timeout <= 0:
                break
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(4096), timeout=silence_timeout,
                )
                if chunk:
                    buf += chunk
                    continue  # bus is active — keep listening
                else:
                    # EOF — peer closed
                    logger.warning("HGM9560: EOF on bus-wait, reconnecting")
                    await self.disconnect()
                    await self.connect()
                    break
            except asyncio.TimeoutError:
                # Silence achieved!
                break
        if buf:
            self._sniff_raw_buffer(buf)
            logger.debug(
                "Bus-wait: flushed %d bytes in %.1fs before silence",
                len(buf), loop.time() - t_start,
            )

    def _sniff_raw_buffer(self, data: bytes) -> None:
        """Parse raw bytes for valid Modbus RTU frames and cache them."""
        if len(data) < 5:
            return
        offset = 0
        bus_key = f"{self.ip}:{self.port}"
        now = _time.monotonic()
        while offset < len(data) - 4:
            fc = data[offset + 1] if offset + 1 < len(data) else 0
            if fc != 0x03:
                offset += 1
                continue
            byte_count = data[offset + 2] if offset + 2 < len(data) else 0
            if byte_count == 0 or byte_count > 250 or byte_count % 2 != 0:
                offset += 1
                continue
            frame_len = 3 + byte_count + 2
            if offset + frame_len > len(data):
                break
            candidate = data[offset:offset + frame_len]
            crc_calc = crc16_modbus(candidate[:-2])
            crc_recv = candidate[-2] | (candidate[-1] << 8)
            if crc_calc != crc_recv:
                offset += 1
                continue
            # Valid frame — cache it
            slave_id = data[offset]
            _bus_sniffed.setdefault(bus_key, {}).setdefault(
                slave_id, {},
            )[byte_count] = (now, parse_read_registers_response(candidate) or [])
            offset += frame_len
        # No logging here — caller logs

    def _save_bonus_frames(self, bonus_frames: list[tuple[int, int, bytes]]) -> None:
        """Save bonus frames from other slaves into the shared bus cache."""
        if not bonus_frames:
            return
        bus_key = f"{self.ip}:{self.port}"
        now = _time.monotonic()
        for bonus_slave, bonus_bc, bonus_frame_data in bonus_frames:
            regs = parse_read_registers_response(bonus_frame_data)
            if regs is not None:
                _bus_sniffed.setdefault(bus_key, {}).setdefault(
                    bonus_slave, {},
                )[bonus_bc] = (now, regs)
                logger.debug(
                    "Sniffed %d regs from slave %d (bc=%d) on bus %s",
                    len(regs), bonus_slave, bonus_bc, bus_key,
                )

    # --- Write with retry (carrier-sense + retry on MSC collision) ----------

    WRITE_MAX_TIME = 10.0  # total deadline for write retries (avoid UI hang)
    WRITE_MAX_ATTEMPTS = 4  # max attempts (bus-wait + send + validate each)

    async def _write_frame_with_retry(
        self, frame: bytes, fc_name: str,
    ) -> None:
        """Send a write frame (FC05/FC06) with carrier-sense and retry.

        Each attempt: bus-wait → send → read echo → validate.
        On validation failure (MSC collision / foreign frame): quick flush → retry.
        Raises ConnectionError after WRITE_MAX_TIME or WRITE_MAX_ATTEMPTS.
        """
        if self._writer is None or self._reader is None:
            await self.connect()

        loop = asyncio.get_event_loop()
        t_start = loop.time()
        deadline = t_start + self.WRITE_MAX_TIME
        last_err: str = ""

        for attempt in range(1, self.WRITE_MAX_ATTEMPTS + 1):
            if loop.time() >= deadline:
                break

            # --- Carrier-sense: wait for bus silence before transmitting ---
            if attempt == 1:
                await self._wait_bus_silence()
            else:
                # After a failed attempt: quick drain then bus-wait
                await self._flush_stale(timeout=0.15)
                remaining = deadline - loop.time()
                if remaining > 0.5:
                    await self._wait_bus_silence()
                # else: almost out of time, just try immediately

            if self._writer is None or self._reader is None:
                await self.connect()

            # --- Send frame ---
            self._writer.write(frame)
            await self._writer.drain()
            await asyncio.sleep(self.INTER_FRAME_DELAY)

            # --- Read echo response ---
            read_timeout = min(self.timeout, max(deadline - loop.time(), 0.5))
            try:
                response = await asyncio.wait_for(
                    self._reader.read(256), timeout=read_timeout,
                )
            except asyncio.TimeoutError:
                last_err = f"{fc_name} timeout (attempt {attempt})"
                logger.warning(
                    "%s: device=%s attempt=%d/%d — timeout, %.1fs elapsed",
                    fc_name, self.device_id, attempt, self.WRITE_MAX_ATTEMPTS,
                    loop.time() - t_start,
                )
                continue

            # --- Validate echo ---
            try:
                _validate_write_echo(frame, response, fc_name)
            except ConnectionError as exc:
                last_err = str(exc)
                # Sniff any MSC data we received instead
                if response:
                    self._sniff_raw_buffer(response)
                logger.warning(
                    "%s: device=%s attempt=%d/%d — %s, %.1fs elapsed",
                    fc_name, self.device_id, attempt, self.WRITE_MAX_ATTEMPTS,
                    exc, loop.time() - t_start,
                )
                continue

            # --- Success ---
            elapsed = loop.time() - t_start
            if attempt > 1:
                logger.info(
                    "%s OK: device=%s addr=0x%04X after %d attempts (%.1fs)",
                    fc_name, self.device_id,
                    struct.unpack(">H", frame[2:4])[0],
                    attempt, elapsed,
                )
            return  # success

        # All attempts exhausted
        elapsed = loop.time() - t_start
        raise ConnectionError(
            f"{fc_name} failed after {self.WRITE_MAX_ATTEMPTS} attempts "
            f"({elapsed:.1f}s): {last_err}"
        )

    async def _send_and_receive(
        self, start: int, count: int, *,
        skip_flush: bool = False,
        quick_flush: bool = False,
    ) -> list[int] | None:
        if self._writer is None or self._reader is None:
            raise ConnectionError("HGM9560: not connected")

        if not skip_flush:
            if quick_flush:
                # Quick drain after error: clear stale data without full bus-wait
                await self._flush_stale(timeout=0.15)
            else:
                # Full bus-wait: listen until silence (carrier sense for MSC gap)
                await self._wait_bus_silence()

        frame = build_read_registers(self.slave_id, start, count)
        expected_bytes = 3 + count * 2 + 2  # slave + fc + bytecount + data + crc

        self._writer.write(frame)
        await self._writer.drain()

        # Wait for device to process request + RS485 turnaround + converter delay
        await asyncio.sleep(self.INTER_FRAME_DELAY)

        response = b""
        got_foreign = False          # True once we received a frame from another slave
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.timeout

        while loop.time() < deadline:
            remaining_time = deadline - loop.time()
            if remaining_time <= 0:
                break

            # ── Foreign frame cap: once we see a foreign response, cap total
            # remaining time — our slave likely won't respond anymore, the
            # foreign data came from a *previous* request's late reply.
            if got_foreign and remaining_time > self.FOREIGN_FRAME_CAP:
                deadline = loop.time() + self.FOREIGN_FRAME_CAP
                remaining_time = self.FOREIGN_FRAME_CAP
                logger.debug(
                    "RTU: foreign frame detected for slave=%d block @%d, "
                    "capping remaining to %.2fs",
                    self.slave_id, start, self.FOREIGN_FRAME_CAP,
                )

            # After receiving foreign data, use shorter read timeout:
            # our response is likely right behind the foreign frame.
            read_timeout = 0.20 if got_foreign else min(remaining_time, 0.5)
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(512),
                    timeout=min(remaining_time, read_timeout),
                )
                if not chunk:
                    raise ConnectionError("HGM9560: connection closed by peer")
                response += chunk

                # Try to find our frame + collect bonus frames from other slaves
                our_frame, bonus_frames = self._extract_all_frames(response, count)
                self._save_bonus_frames(bonus_frames)
                if bonus_frames:
                    got_foreign = True
                if our_frame is not None:
                    return parse_read_registers_response(our_frame)

            except asyncio.TimeoutError:
                if response:
                    break
                return None

        # Last attempt: maybe we have enough data but need to search for frame
        if response:
            our_frame, bonus_frames = self._extract_all_frames(response, count)
            self._save_bonus_frames(bonus_frames)
            if our_frame is not None:
                return parse_read_registers_response(our_frame)

            logger.warning(
                "RTU bad response for block @%d slave=%d: got %d bytes: %s",
                start, self.slave_id, len(response), response[:32].hex(),
            )
        else:
            logger.warning(
                "RTU no response for block @%d slave=%d", start, self.slave_id,
            )
        return None

    def _extract_all_frames(
        self, data: bytes, expected_count: int,
    ) -> tuple[bytes | None, list[tuple[int, int, bytes]]]:
        """Search for ALL valid Modbus RTU response frames in the byte buffer.

        Returns:
            (our_frame, bonus_frames) where:
            - our_frame: bytes of the frame matching self.slave_id + expected_count, or None
            - bonus_frames: list of (slave_id, byte_count, frame_bytes) for other slaves

        The converter may prepend stale bytes from a previous response.
        We scan for any slave_id + FC03 + byte-count, verify CRC, and collect all.
        """
        our_expected_bytes = expected_count * 2
        our_frame: bytes | None = None
        bonus_frames: list[tuple[int, int, bytes]] = []

        offset = 0
        while offset < len(data) - 4:  # need at least 5 bytes for a frame header
            # Check for FC03 response at this offset
            candidate_slave = data[offset]
            fc = data[offset + 1]

            # Exception response (FC | 0x80)
            if fc == (0x03 | 0x80) and candidate_slave == self.slave_id:
                if offset + 5 <= len(data):
                    our_frame = data[offset:offset + 5]
                    offset += 5
                    continue
                break

            if fc != 0x03:
                offset += 1
                continue

            byte_count = data[offset + 2]
            if byte_count == 0 or byte_count > 250 or byte_count % 2 != 0:
                offset += 1
                continue

            frame_len = 3 + byte_count + 2
            if offset + frame_len > len(data):
                # Not enough data — if it's our frame, signal incomplete
                if candidate_slave == self.slave_id and byte_count == our_expected_bytes:
                    break  # our_frame stays None — caller will keep reading
                offset += 1
                continue

            candidate = data[offset:offset + frame_len]
            crc_calc = crc16_modbus(candidate[:-2])
            crc_recv = candidate[-2] | (candidate[-1] << 8)

            if crc_calc != crc_recv:
                offset += 1
                continue

            # Valid CRC — this is a real frame
            if candidate_slave == self.slave_id and byte_count == our_expected_bytes:
                our_frame = candidate
                if offset > 0:
                    logger.debug(
                        "RTU: skipped %d bytes before our frame (slave=%d)",
                        offset, self.slave_id,
                    )
            elif candidate_slave != self.slave_id:
                bonus_frames.append((candidate_slave, byte_count, candidate))

            offset += frame_len  # skip past this frame

        return our_frame, bonus_frames

    # Backward-compatible wrapper (used in _send_and_receive before sniffing)
    def _extract_frame(self, data: bytes, expected_count: int) -> bytes | None:
        our_frame, _ = self._extract_all_frames(data, expected_count)
        return our_frame

    # Blocks that must NEVER use sniffed data — MSC frames can have matching
    # byte_count but contain protocol data, not register values.  Using MSC
    # data as status/accumulated produces phantom alarms and wrong gen_status.
    _NO_SNIFF_BLOCKS = frozenset({"status", "accumulated"})

    def _try_sniffed(self, block_name: str, block: dict, bytecount_map: dict[int, str]) -> list[int] | None:
        """Check bus sniffer cache for a usable frame for this block."""
        if block_name in self._NO_SNIFF_BLOCKS:
            return None  # critical blocks — only direct reads
        bus_key = f"{self.ip}:{self.port}"
        byte_count = block["count"] * 2
        cache = _bus_sniffed.get(bus_key, {}).get(self.slave_id, {})
        entry = cache.get(byte_count)
        if entry is None:
            return None
        ts, cached_regs = entry
        if _time.monotonic() - ts > _SNIFF_TTL:
            return None  # expired
        if len(cached_regs) != block["count"]:
            return None
        # Only use if byte_count uniquely identifies this block
        expected_block = bytecount_map.get(byte_count)
        if expected_block != block_name:
            return None
        # Consume from cache (use once)
        del cache[byte_count]
        logger.debug(
            "Used sniffed data for %s slave=%d device=%s",
            block_name, self.slave_id, self.device_id,
        )
        return cached_regs

    async def read_all(self, *, skip_bus_wait: bool = False) -> dict:
        async with self._lock:
            if self._writer is None or self._reader is None:
                await self.connect()

            self._adaptive_poll_count += 1
            slow_slot = self._adaptive_poll_count % _SLOW_POLL_EVERY

            result: dict = {}
            errors = 0
            total_blocks = len(REGISTER_MAP_9560)
            first_block = True
            # If previous slave on same bus just finished → bus is likely
            # still in MSC quiet window; skip initial bus-wait to save time
            need_bus_wait = not skip_bus_wait  # full bus-wait only at start
            need_quick_flush = False  # quick drain after errors
            consec_fails = 0  # consecutive read failures (MSC collision detector)
            skipped_names: list[str] = []
            blocks_read = 0

            for block_name, block in REGISTER_MAP_9560.items():
                # --- Adaptive: slow blocks spread across slots (max 2 per cycle) ---
                block_slot = _9560_SLOW_SLOTS.get(block_name)
                if block_slot is not None and block_slot != slow_slot:
                    skipped_names.append(block_name)
                    continue

                # --- MSC collision abort: bus is clearly busy ---
                if consec_fails >= 3 and block_name not in self._CRITICAL_BLOCKS:
                    skipped_names.append(block_name + "(abort)")
                    continue

                if not first_block:
                    # Rapid-fire: short delay between blocks of the same slave
                    await asyncio.sleep(self.INTER_BLOCK_DELAY_FAST)
                first_block = False

                # --- Opportunistic sniffing: try cached data first ---
                regs = self._try_sniffed(block_name, block, _9560_BYTECOUNT_MAP)

                if regs is not None:
                    consec_fails = 0  # sniffed data counts as success
                else:
                    # Critical blocks get full retries, others get fast (1) retry
                    max_att = self.MAX_RETRIES if block_name in self._CRITICAL_BLOCKS else self.MAX_RETRIES_FAST
                    for attempt in range(1, max_att + 1):
                        try:
                            regs = await self._send_and_receive(
                                block["address"], block["count"],
                                skip_flush=not (need_bus_wait or need_quick_flush),
                                quick_flush=need_quick_flush and not need_bus_wait,
                            )
                        except ConnectionError:
                            break  # connection lost — skip retries

                        if regs is not None:
                            need_bus_wait = False
                            need_quick_flush = False
                            consec_fails = 0
                            break  # success

                        # Failed — wait for late response, flush, retry
                        if attempt < max_att:
                            logger.debug(
                                "HGM9560 block=%s attempt %d/%d failed, retrying",
                                block_name, attempt, max_att,
                            )
                            await asyncio.sleep(0.15)
                            await self._flush_stale(timeout=0.10)
                            need_bus_wait = False
                            need_quick_flush = False

                if regs is None:
                    logger.warning(
                        "HGM9560 read error block=%s device=%s (after retries)",
                        block_name, self.device_id,
                    )
                    errors += 1
                    consec_fails += 1
                    # After error: quick drain before next block (not full bus-wait)
                    need_quick_flush = True
                    continue

                blocks_read += 1
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

            # ── Status-field protection (HGM9560 / ШПР) ──
            # If status block failed, preserve previous mode flags AND alarms to
            # prevent button/alarm flickering on the frontend.
            _STATUS_KEYS_9560 = ("mode_auto", "mode_manual", "mode_stop",
                                 "mode_test", "alarm_common", "alarm_shutdown",
                                 "alarm_warning", "alarm_trip_stop")
            if not any(k in result for k in _STATUS_KEYS_9560) and self._last_result:
                for k in _STATUS_KEYS_9560:
                    if k in self._last_result:
                        result[k] = self._last_result[k]

            # Merge with cached result: skipped blocks retain previous values
            self._last_result.update(result)

            logger.debug(
                "Adaptive: device=%s cycle=%d, read %d/%d blocks (skipped: %s)",
                self.device_id, self._adaptive_poll_count,
                blocks_read, total_blocks, ", ".join(skipped_names) or "none",
            )

            return self._last_result.copy()

    async def write_coil(self, address: int, value: bool) -> None:
        """FC05 — Write Single Coil via raw RTU frame with carrier-sense retry."""
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            raise ConnectionError(f"Device {self.device_id}: lock timeout on FC05")
        try:
            frame = build_write_coil(self.slave_id, address, value)
            await self._write_frame_with_retry(frame, "FC05")
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

    async def _write_register_unlocked(
        self, address: int, value: int, *, use_retry: bool = True,
    ) -> None:
        """FC06 inner logic — no lock, called from locked context.

        use_retry=True (default): full carrier-sense retry loop (for single writes / first in batch).
        use_retry=False: single-attempt with quick flush only (for subsequent writes in batch).
        """
        frame = build_write_register(self.slave_id, address, value)

        if use_retry:
            await self._write_frame_with_retry(frame, "FC06")
            logger.info(
                "FC06 OK: device=%s addr=0x%04X value=%d",
                self.device_id, address, value,
            )
            return

        # Single-attempt mode (batch writes — bus already acquired)
        if self._writer is None or self._reader is None:
            await self.connect()

        await self._flush_stale(timeout=0.10)

        self._writer.write(frame)
        await self._writer.drain()
        await asyncio.sleep(self.INTER_FRAME_DELAY)

        try:
            response = await asyncio.wait_for(self._reader.read(256), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise ConnectionError("FC06 timeout: no response from HGM9560")

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

    async def _read_registers_unlocked(
        self, address: int, count: int, *, skip_flush: bool = False,
    ) -> list[int]:
        """FC03 inner logic — no lock, called from locked context."""
        if self._writer is None or self._reader is None:
            await self.connect()
        regs = await self._send_and_receive(address, count, skip_flush=skip_flush)
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

    def __init__(self, device: Device, *, site_code: str = ""):
        super().__init__(device, site_code=site_code)
        self._power_logged = False
        # Override adaptive polling for HGM9520N-specific standby detection
        self._last_gen_status: int | None = None

    # connect() inherited from HGM9560Reader — uses shared _rtu_connections

    async def read_all(self, *, skip_bus_wait: bool = False) -> dict:
        async with self._lock:
            if self._writer is None or self._reader is None:
                await self.connect()

            self._adaptive_poll_count += 1
            slow_slot = self._adaptive_poll_count % _SLOW_POLL_EVERY

            # Build skip set based on standby + slot-based slow block rotation
            skip_set: set[str] = set()
            if self._last_gen_status == 0:  # standby — skip live data blocks
                skip_set |= _9520N_STANDBY_SKIP
            # Slow blocks: only read blocks whose slot matches this cycle
            for bname, slot in _9520N_RTU_SLOW_SLOTS.items():
                if slot != slow_slot:
                    skip_set.add(bname)
            # 'status' and 'accumulated' are NEVER skipped (always need gen_status)
            skip_set.discard("status")
            skip_set.discard("accumulated")

            result: dict = {}
            errors = 0
            total_blocks = len(REGISTER_MAP_9520N_RTU)
            first_block = True
            need_bus_wait = not skip_bus_wait  # full bus-wait only at start
            need_quick_flush = False  # quick drain after errors
            consec_fails = 0  # consecutive read failures (MSC collision detector)
            skipped_names: list[str] = []
            blocks_read = 0

            for block_name, block in REGISTER_MAP_9520N_RTU.items():
                # --- Adaptive: skip blocks based on standby + tiered ---
                if block_name in skip_set:
                    skipped_names.append(block_name)
                    continue

                # --- MSC collision abort: bus is clearly busy ---
                if consec_fails >= 3 and block_name not in self._CRITICAL_BLOCKS:
                    skipped_names.append(block_name + "(abort)")
                    continue

                if not first_block:
                    # Rapid-fire: short delay between blocks of the same slave
                    await asyncio.sleep(self.INTER_BLOCK_DELAY_FAST)
                first_block = False

                # --- Opportunistic sniffing: try cached data first ---
                regs = self._try_sniffed(block_name, block, _9520N_RTU_BYTECOUNT_MAP)

                if regs is not None:
                    consec_fails = 0  # sniffed data counts as success
                else:
                    # Critical blocks get full retries, others get fast (1) retry
                    max_att = self.MAX_RETRIES if block_name in self._CRITICAL_BLOCKS else self.MAX_RETRIES_FAST
                    for attempt in range(1, max_att + 1):
                        try:
                            regs = await self._send_and_receive(
                                block["address"], block["count"],
                                skip_flush=not (need_bus_wait or need_quick_flush),
                                quick_flush=need_quick_flush and not need_bus_wait,
                            )
                        except ConnectionError:
                            break  # connection lost — skip retries

                        if regs is not None:
                            need_bus_wait = False
                            need_quick_flush = False
                            consec_fails = 0
                            break  # success

                        # Failed — wait, flush, retry
                        if attempt < max_att:
                            logger.debug(
                                "HGM9520N-RTU block=%s attempt %d/%d failed, retrying",
                                block_name, attempt, max_att,
                            )
                            await asyncio.sleep(0.15)
                            await self._flush_stale(timeout=0.10)
                            need_bus_wait = False
                            need_quick_flush = False

                if regs is None:
                    logger.warning(
                        "HGM9520N-RTU read error block=%s device=%s (after retries)",
                        block_name, self.device_id,
                    )
                    errors += 1
                    consec_fails += 1
                    # After error: quick drain before next block (not full bus-wait)
                    need_quick_flush = True
                    continue

                blocks_read += 1
                for field_name, parser in block["fields"].items():
                    try:
                        result[field_name] = parser(regs)
                    except Exception as exc:
                        logger.debug(
                            "Parse error %s.%s: %s", block_name, field_name, exc,
                        )
                        result[field_name] = None

                # Update standby detection after parsing 'accumulated' block
                if block_name == "accumulated" and "gen_status" in result:
                    self._last_gen_status = result["gen_status"]
                # Log raw power registers once for diagnostics
                if block_name == "gen_current_power" and not self._power_logged:
                    self._power_logged = True
                    logger.info(
                        "Device %s power RAW regs[166-181]=%s → power_total=%.1f kW (RTU)",
                        self.device_id, regs[:16], result.get("power_total", 0),
                    )

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
            if "gen_ats_status" in result:
                code = result["gen_ats_status"]
                result["gen_ats_status_text"] = ATS_STATUS_CODES.get(
                    code, f"unknown_{code}",
                )
            if "mains_ats_status" in result:
                code = result["mains_ats_status"]
                result["mains_ats_status_text"] = ATS_STATUS_CODES.get(
                    code, f"unknown_{code}",
                )

            # Normalize sync parameters
            if "phase_diff" in result and result["phase_diff"] is not None:
                pd = result["phase_diff"]
                if pd > 180:
                    result["phase_diff"] = pd - 360
                elif pd < -180:
                    result["phase_diff"] = pd + 360
                if abs(result["phase_diff"]) > 180:
                    result["phase_diff"] = None

            # ── Status-field protection ──
            # If status block failed to read this cycle, preserve previous
            # mode flags AND alarms from cache to prevent flickering.
            _STATUS_KEYS = ("mode_auto", "mode_manual", "mode_stop",
                            "mode_test", "mode_off", "alarm_common",
                            "alarm_shutdown", "alarm_warning", "alarm_block")
            if not any(k in result for k in _STATUS_KEYS) and self._last_result:
                for k in _STATUS_KEYS:
                    if k in self._last_result:
                        result[k] = self._last_result[k]

            # Merge with cached result: skipped blocks retain previous values
            self._last_result.update(result)

            logger.debug(
                "Adaptive: device=%s cycle=%d, read %d/%d blocks (skipped: %s, gen_status=%s)",
                self.device_id, self._adaptive_poll_count,
                blocks_read, total_blocks,
                ", ".join(skipped_names) or "none",
                self._last_gen_status,
            )

            return self._last_result.copy()


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

    OFFLINE_THRESHOLD = 3  # consecutive failures before publishing online=False

    def __init__(self, redis: Redis, session_factory: async_sessionmaker[AsyncSession]):
        self.redis = redis
        self.session_factory = session_factory
        self._running = False
        self._readers: dict[int, BaseReader] = {}
        self._last_poll: dict[int, float] = {}  # device_id -> last poll timestamp
        self._poll_intervals: dict[int, float] = {}  # device_id -> per-device interval
        self._fail_counts: dict[int, int] = {}  # device_id -> consecutive poll failures

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

        # Group RTU devices by converter (ip:port) — they share one RS485 bus
        # and MUST be polled sequentially through a single TCP connection.
        # TCP devices can be polled in parallel as before.
        rtu_groups: dict[str, list[tuple[int, BaseReader]]] = {}
        tcp_tasks = []

        for device_id, reader in self._readers.items():
            interval = self._poll_intervals.get(device_id, settings.POLL_INTERVAL)
            last = self._last_poll.get(device_id, 0)
            if now - last < interval:
                continue
            self._last_poll[device_id] = now

            if isinstance(reader, (HGM9560Reader, HGM9520NRtuReader)):
                bus_key = f"{reader.ip}:{reader.port}"
                rtu_groups.setdefault(bus_key, []).append((device_id, reader))
            else:
                tcp_tasks.append(self._poll_device(device_id, reader))

        # Each RTU bus group runs as one sequential task
        async def _poll_rtu_bus(group: list[tuple[int, BaseReader]]) -> None:
            # Sort: HGM9520N generators first (slave 1,2), then HGM9560 ATS.
            # One bus-wait at the start finds the MSC quiet window (~1.5-2.3s).
            # All devices polled back-to-back in a single burst to maximize
            # use of the quiet window.  Each device's _send_and_receive
            # handles stale MSC data in its TCP buffer via _extract_all_frames.
            group_sorted = sorted(
                group,
                key=lambda pair: (0 if isinstance(pair[1], HGM9520NRtuReader) else 1, pair[0]),
            )
            for i, (device_id, reader) in enumerate(group_sorted):
                # Only first device does full bus-wait; rest poll immediately
                skip = i > 0
                await self._poll_device(device_id, reader, skip_bus_wait=skip)

        all_tasks = list(tcp_tasks)
        for bus_key, group in rtu_groups.items():
            all_tasks.append(_poll_rtu_bus(group))

        if all_tasks:
            t0 = _time.monotonic()
            await asyncio.gather(*all_tasks, return_exceptions=True)
            elapsed = _time.monotonic() - t0
            logger.info("Poll cycle: %d tasks, %.1fs", len(all_tasks), elapsed)

    def _get_cached_data(self, reader: BaseReader) -> dict:
        """Return cached _last_result data from reader, if available."""
        return getattr(reader, '_last_result', {}).copy()

    async def _poll_device(self, device_id: int, reader: BaseReader, *, skip_bus_wait: bool = False) -> None:
        try:
            data = await reader.read_all(skip_bus_wait=skip_bus_wait)
            if not data:
                logger.warning("Device %s: read_all returned empty data", device_id)
                self._fail_counts[device_id] = self._fail_counts.get(device_id, 0) + 1
                if self._fail_counts[device_id] >= self.OFFLINE_THRESHOLD:
                    # Publish cached data with online=false so frontend keeps
                    # previously known values (modes, alarms) in disabled state
                    cached = self._get_cached_data(reader)
                    await self._publish(device_id, reader, cached, online=False, error="no data received")
                    logger.warning("Device %s offline: %d consecutive failures", device_id, self._fail_counts[device_id])
                await reader.disconnect()
            else:
                if self._fail_counts.get(device_id, 0) > 0:
                    logger.info("Device %s back online after %d failures", device_id, self._fail_counts[device_id])
                self._fail_counts[device_id] = 0
                await self._publish(device_id, reader, data, online=True)
        except Exception as exc:
            self._fail_counts[device_id] = self._fail_counts.get(device_id, 0) + 1
            logger.error(
                "Poll error device=%s (%s): %s (fail %d/%d)",
                device_id, reader.ip, exc,
                self._fail_counts[device_id], self.OFFLINE_THRESHOLD,
            )
            if self._fail_counts[device_id] >= self.OFFLINE_THRESHOLD:
                cached = self._get_cached_data(reader)
                await self._publish(device_id, reader, cached, online=False, error=str(exc))
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

        # Build controller_time from RTC registers (225-231) if available (HGM9560 only)
        _rsec = data.get("rtc_sec")
        _rmin = data.get("rtc_min")
        _rhour = data.get("rtc_hour")
        _rday = data.get("rtc_day")
        _rmonth = data.get("rtc_month")
        _ryear = data.get("rtc_year")
        if all(v is not None for v in (_rsec, _rmin, _rhour, _rday, _rmonth, _ryear)):
            s, mi, h, d, mo, y = int(_rsec), int(_rmin), int(_rhour), int(_rday), int(_rmonth), int(_ryear)
            # Range validation before constructing datetime
            if 0 <= s <= 59 and 0 <= mi <= 59 and 0 <= h <= 23 and 1 <= d <= 31 and 1 <= mo <= 12 and y > 0:
                try:
                    yr = y if y > 2000 else y + 2000
                    ct = datetime(yr, mo, d, h, mi, s)
                    payload["controller_time"] = ct.isoformat()
                except (ValueError, OverflowError, TypeError):
                    pass

        json_str = json.dumps(payload, default=str)
        redis_key = f"device:{device_id}:metrics"

        # TTL 300s — long enough for RTU buses with 3+ devices
        # (sequential poll of 3 devices × 15 blocks can take 2-3 minutes)
        await self.redis.set(redis_key, json_str, ex=300)
        await self.redis.publish("metrics:updates", json_str)

        if online:
            logger.debug("Published metrics for device %s", device_id)
        else:
            logger.warning("Device %s offline: %s", device_id, error)
