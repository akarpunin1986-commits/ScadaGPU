"""
САНЁК v4 — Modbus tools.

read_modbus_register — direct register read from SmartGen controllers
send_modbus_command — write register with pending confirmation flow
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta

from config import settings
from services.sanek_v4.device_map import DEVICE_MAP
from services.sanek_v4.tools import registry

logger = logging.getLogger("sanek_v4.tools.modbus")

COMMAND_TTL = 300  # 5 minutes

# Known register descriptions for HGM9520N
REGISTER_NAMES_9520N = {
    0: ("Status Coils", None, None),
    1: ("Genset L1-N Voltage", 0.1, "V"),
    2: ("Genset L2-N Voltage", 0.1, "V"),
    3: ("Genset L3-N Voltage", 0.1, "V"),
    5: ("Genset Frequency", 0.01, "Hz"),
    12: ("Active Power Total", 0.001, "kW"),  # 4 bytes
    212: ("Engine Speed", 1, "RPM"),
    213: ("Coolant Temperature", 0.1, "°C"),
    214: ("Oil Pressure", 1, "kPa"),
    215: ("Oil Temperature", 0.1, "°C"),
    219: ("Fuel Level", 1, "%"),
    220: ("Load Percent", 0.1, "%"),
    241: ("Fuel Consumption", 0.1, "L/h"),
    260: ("Run Hours", None, "hours"),
}

# Remote coil names for HGM9520N (FC05)
COIL_NAMES_9520N = {
    0: "Remote Start", 1: "Remote Stop", 3: "Remote Auto", 4: "Remote Manual",
    12: "Remote Mute", 15: "Fast Stop", 17: "Alarm Reset",
}

COIL_NAMES_9560 = {
    0: "Remote Start", 1: "Remote Stop", 3: "Remote Auto", 4: "Remote Manual",
    5: "Mains Close/Open", 6: "Busbar Close/Open", 12: "Mute",
}


# ═══════════════════════════════════════════════════════════════
# TOOL: read_modbus_register
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="read_modbus_register",
    description=(
        "Прочитать Modbus регистр напрямую с контроллера SmartGen. "
        "Используй когда нужен параметр, которого нет в стандартных метриках БД, "
        "или для верификации данных из PostgreSQL свежим чтением с оборудования. "
        "Function code 03H (read holding registers). "
        "⚠️ RS-485 шина может давать ~30сек non-response из-за MSC collisions — это нормально."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "enum": ["mkz_gen1", "mkz_gen2", "yakz_gen1", "yakz_gen2", "mkz_panel", "yakz_panel"],
                "description": "Устройство для чтения.",
            },
            "register_address": {
                "type": "integer",
                "description": (
                    "Modbus register address (decimal). "
                    "HGM9520N: 0=Status, 1=GenVoltage(×0.1V), 5=Frequency(×0.01Hz), "
                    "12=ActivePower(×0.001kW), 212=RPM, 213=Coolant(×0.1°C), "
                    "214=OilPressure(kPa), 241=FuelConsumption. "
                    "HGM9560: 0=SystemStatus, 1=MainsVoltageL1."
                ),
            },
            "register_count": {
                "type": "integer",
                "description": "Количество consecutive регистров (1-10). По умолчанию 1.",
            },
        },
        "required": ["device_id", "register_address"],
    },
)
async def read_modbus_register(
    device_id: str,
    register_address: int,
    register_count: int = 1,
) -> dict:
    """Read holding registers via existing Modbus service."""
    dev = DEVICE_MAP.get(device_id)
    if not dev:
        return {"error": f"Unknown device: {device_id}"}

    register_count = max(1, min(10, register_count))

    # Use existing commands API to read registers
    try:
        import httpx
        # Call internal API which handles Modbus connection pooling
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Use the existing modbus read via internal endpoint
            resp = await client.get(
                f"http://localhost:8000/api/devices/{dev['device_id']}/registers",
                params={"address": register_address, "count": register_count},
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_values = data.get("values", [])
            elif resp.status_code == 404:
                # Endpoint doesn't exist - use direct read via modbus_poller
                raw_values = await _direct_modbus_read(dev, register_address, register_count)
            else:
                return {"error": f"Internal API error: {resp.status_code}", "device": device_id}
    except httpx.TimeoutException:
        return {
            "error": "ModbusTimeout",
            "message": (
                f"Device {device_id} не ответил за 10 секунд. "
                "Это может быть нормальным (RS-485 MSC collision). "
                "Попробуйте ещё раз через 30 секунд."
            ),
            "device": device_id,
            "register": register_address,
        }
    except Exception as e:
        # Fallback: direct read
        try:
            raw_values = await _direct_modbus_read(dev, register_address, register_count)
        except Exception as e2:
            return {"error": f"Read failed: {str(e2)}", "device": device_id, "register": register_address}

    # Interpret known registers
    controller = dev["controller"]
    interpreted = None
    if controller == "HGM9520N" and register_address in REGISTER_NAMES_9520N:
        name, ratio, unit = REGISTER_NAMES_9520N[register_address]
        if ratio and raw_values:
            interpreted = {
                "name": name,
                "value": round(raw_values[0] * ratio, 3),
                "unit": unit,
                "ratio": ratio,
            }
        else:
            interpreted = {"name": name}

    result = {
        "device": device_id,
        "controller": controller,
        "register": register_address,
        "register_count": register_count,
        "raw_values": raw_values,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if interpreted:
        result["interpreted"] = interpreted
    return result


async def _direct_modbus_read(dev: dict, address: int, count: int) -> list[int]:
    """Direct Modbus read using the existing poller infrastructure."""
    from sqlalchemy import select
    from models.base import async_session
    from models.device import Device

    db_id = dev["device_id"]

    async with async_session() as db:
        device = (await db.execute(select(Device).where(Device.id == db_id))).scalar_one_or_none()
        if not device:
            raise ValueError(f"Device {db_id} not found in DB")

    # Use pymodbus for TCP devices, raw socket for RTU
    if device.protocol.value == "tcp":
        from pymodbus.client import AsyncModbusTcpClient
        client = AsyncModbusTcpClient(device.ip_address, port=device.port, timeout=5)
        await client.connect()
        try:
            resp = await client.read_holding_registers(address, count, slave=device.slave_id)
            if resp.isError():
                raise RuntimeError(f"Modbus error: {resp}")
            return list(resp.registers)
        finally:
            client.close()
    else:
        # RTU over TCP - use raw frame
        import asyncio
        import struct

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(device.ip_address, device.port),
            timeout=5.0,
        )
        try:
            frame = _build_fc03_frame(device.slave_id, address, count)
            writer.write(frame)
            await writer.drain()
            response = await asyncio.wait_for(reader.read(256), timeout=5.0)
            if len(response) < 5:
                raise RuntimeError(f"Short response: {response.hex()}")
            # Parse FC03 response
            byte_count = response[2]
            values = []
            for i in range(byte_count // 2):
                values.append(struct.unpack(">H", response[3 + i*2: 5 + i*2])[0])
            return values
        finally:
            writer.close()


def _build_fc03_frame(slave: int, start: int, count: int) -> bytes:
    """Build Modbus RTU FC03 frame with CRC."""
    import struct
    frame = struct.pack(">BBHH", slave, 3, start, count)
    crc = _crc16(frame)
    return frame + struct.pack("<H", crc)


def _crc16(data: bytes) -> int:
    """CRC-16/Modbus."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


# ═══════════════════════════════════════════════════════════════
# TOOL: send_modbus_command
# ═══════════════════════════════════════════════════════════════

@registry.tool(
    name="send_modbus_command",
    description=(
        "Записать значение в Modbus регистр контроллера. "
        "⚠️ ОПАСНАЯ ОПЕРАЦИЯ — влияет на физическое оборудование. "
        "Команда НЕ выполняется сразу — создаёт запрос на подтверждение оператором. "
        "Только после подтверждения происходит реальная запись. TTL: 5 минут.\n\n"
        "ОГРАНИЧЕНИЯ:\n"
        "- HGM9560 firmware Dec 2013: write registers 4351-4354 могут не работать\n"
        "- Remote commands (function 05H) отправляются однократно (one-shot)\n\n"
        "Используй ТОЛЬКО когда оператор ЯВНО попросил действие."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "device_id": {
                "type": "string",
                "enum": ["mkz_gen1", "mkz_gen2", "yakz_gen1", "yakz_gen2", "mkz_panel", "yakz_panel"],
                "description": "Целевое устройство.",
            },
            "action": {
                "type": "string",
                "description": (
                    "Описание действия для оператора. "
                    "Примеры: 'Переключить Gen1 МКЗ в Auto', 'Remote Stop Gen2 ЯКЗ'."
                ),
            },
            "register_address": {
                "type": "integer",
                "description": (
                    "HGM9520N Remote Coils (FC05): "
                    "0=Start, 1=Stop, 3=Auto, 4=Manual, 12=Mute, 15=FastStop, 17=AlarmReset. "
                    "HGM9560 Remote Coils (FC05): "
                    "0=Start, 1=Stop, 3=Auto, 4=Manual, 5=MainsClose, 6=BusbarClose, 12=Mute."
                ),
            },
            "value": {
                "type": "integer",
                "description": "FC05: 0xFF00 (65280) activate, 0x0000 deactivate. FC06: uint16.",
            },
            "function_code": {
                "type": "string",
                "enum": ["05", "06"],
                "description": "'05' = Write Coil. '06' = Write Register.",
            },
        },
        "required": ["device_id", "action", "register_address", "value", "function_code"],
    },
)
async def send_modbus_command(
    device_id: str,
    action: str,
    register_address: int,
    value: int,
    function_code: str,
) -> dict:
    """Create pending command in Redis for operator confirmation."""
    dev = DEVICE_MAP.get(device_id)
    if not dev:
        return {"status": "error", "message": f"Unknown device: {device_id}"}

    # HGM9560 firmware limitation
    if dev["controller"] == "HGM9560" and register_address in range(4351, 4355):
        return {
            "status": "warning",
            "message": (
                "⚠️ HGM9560 firmware Dec 2013 (до Protocol V1.1). "
                "Регистры 4351-4354 могут не работать удалённо. "
                "Рекомендуется выполнить через интерфейс контроллера на месте."
            ),
        }

    command_id = f"cmd_{uuid.uuid4().hex[:12]}"

    # Get coil name for display
    controller = dev["controller"]
    coil_names = COIL_NAMES_9520N if controller == "HGM9520N" else COIL_NAMES_9560
    register_name = coil_names.get(register_address, f"Register {register_address}")

    command_data = {
        "command_id": command_id,
        "device_id": device_id,
        "device_db_id": dev["device_id"],
        "controller": controller,
        "device_name": dev["name"],
        "action": action,
        "register_address": register_address,
        "register_name": register_name,
        "value": value,
        "value_hex": f"0x{value:04X}",
        "function_code": function_code,
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": (datetime.utcnow() + timedelta(seconds=COMMAND_TTL)).isoformat(),
        "status": "pending",
    }

    # Save to Redis with TTL
    try:
        from redis.asyncio import Redis as AioRedis
        redis = AioRedis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await redis.setex(
                f"sanek:cmd:{command_id}",
                COMMAND_TTL,
                json.dumps(command_data, ensure_ascii=False),
            )
        finally:
            await redis.close()
    except Exception as e:
        logger.error("Failed to save pending command to Redis: %s", e)
        return {"status": "error", "message": f"Failed to queue command: {str(e)}"}

    # Also log to command_log table
    try:
        from sqlalchemy import text
        from models.base import async_session
        async with async_session() as db:
            await db.execute(
                text("""
                    INSERT INTO sanek_command_log
                        (command_id, device_id, action, register_address, value, function_code, status)
                    VALUES (:cid, :did, :act, :reg, :val, :fc, 'pending')
                """),
                {"cid": command_id, "did": device_id, "act": action,
                 "reg": register_address, "val": value, "fc": function_code},
            )
            await db.commit()
    except Exception as e:
        logger.warning("Failed to log command: %s", e)

    return {
        "status": "pending_confirmation",
        "command_id": command_id,
        "message": f"Команда '{action}' ожидает подтверждения оператором.",
        "details": {
            "device": device_id,
            "device_name": dev["name"],
            "controller": controller,
            "register": register_address,
            "register_name": register_name,
            "value": f"0x{value:04X}",
            "function_code": f"0{function_code}H",
            "expires_in_seconds": COMMAND_TTL,
        },
    }
