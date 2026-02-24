import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Device, DeviceType, ModbusProtocol, Site, get_session

logger = logging.getLogger("scada.devices")

router = APIRouter(prefix="/api/devices", tags=["devices"])


# --- Schemas ---

class DeviceCreate(BaseModel):
    site_id: int
    name: str
    device_type: DeviceType
    ip_address: str
    port: int = 502
    slave_id: int = 1
    protocol: ModbusProtocol
    is_active: bool = True
    description: str | None = None
    poll_interval: float | None = None
    modbus_timeout: float | None = None
    retry_delay: float | None = None


class DeviceUpdate(BaseModel):
    name: str | None = None
    device_type: DeviceType | None = None
    ip_address: str | None = None
    port: int | None = None
    slave_id: int | None = None
    protocol: ModbusProtocol | None = None
    is_active: bool | None = None
    description: str | None = None
    poll_interval: float | None = None
    modbus_timeout: float | None = None
    retry_delay: float | None = None


class DeviceOut(BaseModel):
    id: int
    site_id: int
    name: str
    device_type: DeviceType
    ip_address: str
    port: int
    slave_id: int
    protocol: ModbusProtocol
    is_active: bool
    description: str | None
    poll_interval: float | None
    modbus_timeout: float | None
    retry_delay: float | None

    model_config = {"from_attributes": True}


# --- Endpoints ---

@router.get("", response_model=list[DeviceOut])
async def list_devices(
    site_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Device).order_by(Device.id)
    if site_id is not None:
        stmt = stmt.where(Device.site_id == site_id)
    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int, session: AsyncSession = Depends(get_session)):
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    return device


@router.post("", response_model=DeviceOut, status_code=201)
async def create_device(
    data: DeviceCreate, request: Request, session: AsyncSession = Depends(get_session)
):
    site = await session.get(Site, data.site_id)
    if not site:
        raise HTTPException(404, "Site not found")
    device = Device(**data.model_dump())
    session.add(device)
    await session.commit()
    await session.refresh(device)
    await request.app.state.redis.publish("poller:reload", "device_created")
    return device


@router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    data: DeviceUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    await session.commit()
    await session.refresh(device)
    await request.app.state.redis.publish("poller:reload", "device_updated")
    return device


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    await session.delete(device)
    await session.commit()
    await request.app.state.redis.publish("poller:reload", "device_deleted")


# --- Connection Test ---

class ConnectionTestRequest(PydanticBaseModel):
    ip_address: str
    port: int = 502
    slave_id: int = 1
    protocol: ModbusProtocol


class ConnectionTestResponse(PydanticBaseModel):
    success: bool
    message: str
    data: dict | None = None


def _find_active_reader(request: Request, ip: str, port: int, slave_id: int):
    """Find an existing poller reader for the given IP:port:slave.

    RS485 converters typically support only one TCP connection at a time,
    so we must reuse the poller's connection instead of opening a competing one.
    """
    poller = getattr(request.app.state, "poller", None)
    if poller is None:
        return None
    readers = getattr(poller, "_readers", {})
    for reader in readers.values():
        if reader.ip == ip and reader.port == port and reader.slave_id == slave_id:
            return reader
    return None


@router.post("/test-connection", response_model=ConnectionTestResponse)
async def test_connection(req: ConnectionTestRequest, request: Request):
    """Test connection to a controller: connect and read status register.

    For RTU-over-TCP: reuses existing poller reader if available (RS485 converters
    typically support only one TCP connection at a time).
    """
    import asyncio

    try:
        if req.protocol == ModbusProtocol.TCP:
            # --- Modbus TCP: try existing reader first, fallback to new connection ---
            existing = _find_active_reader(request, req.ip_address, req.port, req.slave_id)
            if existing:
                logger.info(
                    "test-connection reusing active TCP reader for %s:%s slave=%s",
                    req.ip_address, req.port, req.slave_id,
                )
                try:
                    regs = await existing.read_registers_batch([(0, 1)])
                    status_word = regs[0][0]
                    return ConnectionTestResponse(
                        success=True,
                        message=f"HGM9520N OK (via poller). Status: 0x{status_word:04X}",
                        data={"status_register": status_word, "via_poller": True},
                    )
                except Exception as e:
                    logger.warning("test-connection via existing TCP reader failed: %s, fallback", e)

            from pymodbus.client import AsyncModbusTcpClient
            client = AsyncModbusTcpClient(
                host=req.ip_address,
                port=req.port,
                timeout=3,
            )
            connected = await client.connect()
            if not connected:
                return ConnectionTestResponse(
                    success=False,
                    message=f"Cannot connect to {req.ip_address}:{req.port}",
                )
            try:
                resp = await client.read_holding_registers(
                    address=0, count=1, slave=req.slave_id,
                )
                if resp.isError():
                    return ConnectionTestResponse(
                        success=False,
                        message=f"Modbus error: {resp}",
                    )
                status_word = resp.registers[0]
                return ConnectionTestResponse(
                    success=True,
                    message=f"HGM9520N connected OK. Status register: 0x{status_word:04X}",
                    data={"status_register": status_word},
                )
            finally:
                client.close()

        else:
            # --- RTU-over-TCP: MUST reuse existing reader (RS485 = 1 connection only) ---
            existing = _find_active_reader(request, req.ip_address, req.port, req.slave_id)
            if existing:
                logger.info(
                    "test-connection reusing active RTU reader for %s:%s slave=%s",
                    req.ip_address, req.port, req.slave_id,
                )
                try:
                    regs = await existing.read_registers_batch([(0, 1)])
                    status = regs[0]
                    return ConnectionTestResponse(
                        success=True,
                        message=f"RTU OK (via poller). Status: 0x{status[0]:04X}",
                        data={"status_register": status[0], "registers_count": len(status), "via_poller": True},
                    )
                except Exception as e:
                    logger.warning("test-connection via existing RTU reader failed: %s, fallback to new conn", e)

            # Fallback: open new connection (device not in poller yet)
            logger.info(
                "test-connection opening new RTU connection to %s:%s slave=%s",
                req.ip_address, req.port, req.slave_id,
            )
            from services.modbus_poller import build_read_registers, parse_read_registers_response

            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(req.ip_address, req.port),
                    timeout=3,
                )
            except (asyncio.TimeoutError, OSError) as e:
                return ConnectionTestResponse(
                    success=False,
                    message=f"Cannot connect to {req.ip_address}:{req.port}: {e}",
                )

            try:
                await asyncio.sleep(0.05)

                frame = build_read_registers(req.slave_id, 0, 1)
                writer.write(frame)
                await writer.drain()

                await asyncio.sleep(0.15)

                response = b""
                expected = 3 + 1 * 2 + 2
                deadline = asyncio.get_event_loop().time() + 3

                while asyncio.get_event_loop().time() < deadline:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        chunk = await asyncio.wait_for(
                            reader.read(256),
                            timeout=min(remaining, 0.5),
                        )
                        if not chunk:
                            break
                        response += chunk
                        if len(response) >= 5 and response[1] == 0x03:
                            frame_len = 3 + response[2] + 2
                            if len(response) >= frame_len:
                                break
                    except asyncio.TimeoutError:
                        break

                regs = parse_read_registers_response(response)
                if regs is None:
                    return ConnectionTestResponse(
                        success=False,
                        message=f"No valid response. Raw: {response.hex() if response else 'empty'}",
                    )
                return ConnectionTestResponse(
                    success=True,
                    message=f"RTU connected OK. Status: 0x{regs[0]:04X}",
                    data={"status_register": regs[0], "registers_count": len(regs)},
                )
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    except Exception as exc:
        return ConnectionTestResponse(
            success=False,
            message=f"Error: {exc}",
        )
