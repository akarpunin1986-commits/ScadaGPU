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
        "address": 109, "count": 10,
        "fields": {
            "mains_total_p": lambda regs: _signed32(regs[0], regs[1]) * 0.1,
            "mains_total_q": lambda regs: _signed32(regs[8], regs[9]) * 0.1,
        },
    },
    "busbar_misc": {
        "address": 134, "count": 12,
        "fields": {
            "busbar_current": lambda regs: regs[0] * 0.1,
            "battery_v":      lambda regs: regs[8] * 0.1,
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
    def __init__(self, device: Device):
        self.device = device
        self.device_id = device.id
        self.ip = device.ip_address
        self.port = device.port
        self.slave_id = device.slave_id

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def read_all(self) -> dict: ...


# ---------------------------------------------------------------------------
# HGM9520N Reader — Modbus TCP (pymodbus)
# ---------------------------------------------------------------------------

class HGM9520NReader(BaseReader):
    """Modbus TCP via pymodbus AsyncModbusTcpClient."""

    def __init__(self, device: Device):
        super().__init__(device)
        self._client: AsyncModbusTcpClient | None = None

    async def connect(self) -> None:
        self._client = AsyncModbusTcpClient(
            host=self.ip,
            port=self.port,
            timeout=settings.MODBUS_TIMEOUT,
        )
        connected = await self._client.connect()
        if not connected:
            raise ConnectionError(
                f"HGM9520N: cannot connect to {self.ip}:{self.port}"
            )
        logger.info("HGM9520N connected: %s:%s slave=%s", self.ip, self.port, self.slave_id)

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    async def read_all(self) -> dict:
        if not self._client or not self._client.connected:
            await self.connect()

        result: dict = {}
        for block_name, block in REGISTER_MAP_9520N.items():
            resp = await self._client.read_holding_registers(
                address=block["address"],
                count=block["count"],
                slave=self.slave_id,
            )
            if resp.isError():
                logger.warning(
                    "HGM9520N read error block=%s device=%s: %s",
                    block_name, self.device_id, resp,
                )
                continue
            regs = list(resp.registers)
            for field_name, parser in block["fields"].items():
                try:
                    result[field_name] = parser(regs)
                except Exception as exc:
                    logger.debug("Parse error %s.%s: %s", block_name, field_name, exc)
                    result[field_name] = None

        if "gen_status" in result:
            code = result["gen_status"]
            result["gen_status_text"] = GEN_STATUS_CODES.get(code, f"unknown_{code}")

        return result


# ---------------------------------------------------------------------------
# HGM9560 Reader — RTU over TCP (raw socket + CRC16)
# ---------------------------------------------------------------------------

class HGM9560Reader(BaseReader):
    """Modbus RTU over TCP via raw asyncio socket."""

    INTER_FRAME_DELAY = 0.15
    INTER_BLOCK_DELAY = 0.05

    def __init__(self, device: Device):
        super().__init__(device)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.ip, self.port),
            timeout=settings.MODBUS_TIMEOUT,
        )
        logger.info("HGM9560 connected: %s:%s slave=%s", self.ip, self.port, self.slave_id)

    async def disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def _flush_stale(self) -> None:
        """Drain any stale bytes sitting in the buffer."""
        if self._reader is None:
            return
        try:
            stale = await asyncio.wait_for(self._reader.read(1024), timeout=0.05)
            if stale:
                logger.debug("HGM9560: flushed %d stale bytes", len(stale))
            if not stale:
                raise ConnectionError("HGM9560: connection closed by peer (EOF on flush)")
        except asyncio.TimeoutError:
            pass

    async def _send_and_receive(self, start: int, count: int) -> list[int] | None:
        if self._writer is None or self._reader is None:
            raise ConnectionError("HGM9560: not connected")

        await self._flush_stale()

        frame = build_read_registers(self.slave_id, start, count)
        self._writer.write(frame)
        await self._writer.drain()

        await asyncio.sleep(self.INTER_FRAME_DELAY)

        expected_bytes = 3 + count * 2 + 2  # slave + fc + bytecount + data + crc
        response = b""
        deadline = asyncio.get_event_loop().time() + settings.MODBUS_TIMEOUT

        while asyncio.get_event_loop().time() < deadline:
            remaining_time = deadline - asyncio.get_event_loop().time()
            if remaining_time <= 0:
                break
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(256),
                    timeout=min(remaining_time, 0.5),
                )
                if not chunk:
                    raise ConnectionError("HGM9560: connection closed by peer")
                response += chunk

                if len(response) >= 5:
                    if response[1] == 0x03:
                        frame_len = 3 + response[2] + 2
                        if len(response) >= frame_len:
                            response = response[:frame_len]
                            break
                    elif response[1] & 0x80:
                        if len(response) >= 5:
                            break
            except asyncio.TimeoutError:
                if response:
                    break
                return None

        if len(response) < 5:
            logger.warning(
                "HGM9560 incomplete response for block @%d: got %d bytes: %s",
                start, len(response), response.hex() if response else "empty",
            )
            return None

        return parse_read_registers_response(response)

    async def read_all(self) -> dict:
        if self._writer is None or self._reader is None:
            await self.connect()

        result: dict = {}
        first_block = True
        for block_name, block in REGISTER_MAP_9560.items():
            if not first_block:
                await asyncio.sleep(self.INTER_BLOCK_DELAY)
            first_block = False

            regs = await self._send_and_receive(block["address"], block["count"])
            if regs is None:
                logger.warning(
                    "HGM9560 read error block=%s device=%s",
                    block_name, self.device_id,
                )
                continue

            for field_name, parser in block["fields"].items():
                try:
                    result[field_name] = parser(regs)
                except Exception as exc:
                    logger.debug("Parse error %s.%s: %s", block_name, field_name, exc)
                    result[field_name] = None

        if not result:
            logger.warning("HGM9560 device=%s: all blocks returned empty", self.device_id)

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


# ---------------------------------------------------------------------------
# ModbusPoller — main polling orchestrator
# ---------------------------------------------------------------------------

def _make_reader(device: Device) -> BaseReader:
    if device.protocol == ModbusProtocol.TCP:
        return HGM9520NReader(device)
    return HGM9560Reader(device)


class ModbusPoller:
    """Background poller: reads devices from DB, polls via Modbus, publishes to Redis."""

    def __init__(self, redis: Redis, session_factory: async_sessionmaker[AsyncSession]):
        self.redis = redis
        self.session_factory = session_factory
        self._running = False
        self._readers: dict[int, BaseReader] = {}

    async def _load_devices(self) -> list[Device]:
        async with self.session_factory() as session:
            stmt = select(Device).where(Device.is_active == True)  # noqa: E712
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def start(self) -> None:
        self._running = True
        logger.info("ModbusPoller starting...")

        devices = await self._load_devices()
        if not devices:
            logger.warning("No active devices found in DB")

        for dev in devices:
            self._readers[dev.id] = _make_reader(dev)
            logger.info(
                "Registered reader for device %s (%s) at %s:%s [%s]",
                dev.id, dev.name, dev.ip_address, dev.port, dev.protocol.value,
            )

        self._reload_requested = False
        self._reload_task = asyncio.create_task(self._listen_reload())

        while self._running:
            if self._reload_requested:
                self._reload_requested = False
                await self.reload_devices()
            await self._poll_cycle()
            await asyncio.sleep(settings.POLL_INTERVAL)

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

        for dev in new_devices:
            existing_reader = self._readers.get(dev.id)
            if existing_reader:
                if (existing_reader.ip != dev.ip_address
                        or existing_reader.port != dev.port
                        or existing_reader.slave_id != dev.slave_id):
                    logger.info(
                        "Device %s config changed (%s:%s -> %s:%s), reconnecting",
                        dev.id, existing_reader.ip, existing_reader.port,
                        dev.ip_address, dev.port,
                    )
                    try:
                        await existing_reader.disconnect()
                    except Exception:
                        pass
                    self._readers[dev.id] = _make_reader(dev)
            else:
                logger.info(
                    "New device %s (%s) at %s:%s [%s]",
                    dev.id, dev.name, dev.ip_address, dev.port, dev.protocol.value,
                )
                self._readers[dev.id] = _make_reader(dev)

        logger.info("ModbusPoller: reload complete. Active readers: %d", len(self._readers))

    async def _listen_reload(self) -> None:
        """Listen to Redis channel poller:reload for hot-reload signals."""
        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe("poller:reload")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    logger.info("Received reload signal")
                    self._reload_requested = True
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Reload listener error: %s", exc)

    async def _poll_cycle(self) -> None:
        tasks = [
            self._poll_device(device_id, reader)
            for device_id, reader in self._readers.items()
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll_device(self, device_id: int, reader: BaseReader) -> None:
        try:
            data = await reader.read_all()
            if not data:
                logger.warning("Device %s: read_all returned empty data", device_id)
                await self._publish(device_id, reader.device, {}, online=False, error="no data received")
            else:
                await self._publish(device_id, reader.device, data, online=True)
        except Exception as exc:
            logger.error(
                "Poll error device=%s (%s): %s",
                device_id, reader.ip, exc,
            )
            await self._publish(device_id, reader.device, {}, online=False, error=str(exc))
            try:
                await reader.disconnect()
            except Exception:
                pass
            await asyncio.sleep(settings.MODBUS_RETRY_DELAY)

    async def _publish(
        self,
        device_id: int,
        device: Device,
        data: dict,
        *,
        online: bool,
        error: str | None = None,
    ) -> None:
        site_code = ""
        try:
            async with self.session_factory() as session:
                from models.site import Site
                dev = await session.get(Device, device_id)
                if dev:
                    site = await session.get(Site, dev.site_id)
                    if site:
                        site_code = site.code
        except Exception:
            pass

        payload = {
            "device_id": device_id,
            "site_code": site_code,
            "device_type": device.device_type.value if device.device_type else "unknown",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "online": online,
            "error": error,
            **data,
        }

        json_str = json.dumps(payload, default=str)
        redis_key = f"device:{device_id}:metrics"

        await self.redis.set(redis_key, json_str)
        await self.redis.publish("metrics:updates", json_str)

        if online:
            logger.debug("Published metrics for device %s", device_id)
        else:
            logger.warning("Device %s offline: %s", device_id, error)
