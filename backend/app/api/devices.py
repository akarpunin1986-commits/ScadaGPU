from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Device, DeviceType, ModbusProtocol, Site, get_session

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


class DeviceUpdate(BaseModel):
    name: str | None = None
    device_type: DeviceType | None = None
    ip_address: str | None = None
    port: int | None = None
    slave_id: int | None = None
    protocol: ModbusProtocol | None = None
    is_active: bool | None = None
    description: str | None = None


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
    data: DeviceCreate, session: AsyncSession = Depends(get_session)
):
    # Verify site exists
    site = await session.get(Site, data.site_id)
    if not site:
        raise HTTPException(404, "Site not found")
    device = Device(**data.model_dump())
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return device


@router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    data: DeviceUpdate,
    session: AsyncSession = Depends(get_session),
):
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    await session.commit()
    await session.refresh(device)
    return device


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: int, session: AsyncSession = Depends(get_session)):
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    await session.delete(device)
    await session.commit()
