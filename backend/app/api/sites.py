from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Site, get_session

router = APIRouter(prefix="/api/sites", tags=["sites"])


# --- Schemas ---

class SiteCreate(BaseModel):
    name: str
    code: str
    network: str
    description: str | None = None
    is_active: bool = True


class SiteUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    network: str | None = None
    description: str | None = None
    is_active: bool | None = None


class SiteOut(BaseModel):
    id: int
    name: str
    code: str
    network: str
    description: str | None
    is_active: bool

    model_config = {"from_attributes": True}


# --- Endpoints ---

@router.get("", response_model=list[SiteOut])
async def list_sites(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Site).order_by(Site.id))
    return result.scalars().all()


@router.get("/{site_id}", response_model=SiteOut)
async def get_site(site_id: int, session: AsyncSession = Depends(get_session)):
    site = await session.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Site not found")
    return site


@router.post("", response_model=SiteOut, status_code=201)
async def create_site(data: SiteCreate, session: AsyncSession = Depends(get_session)):
    site = Site(**data.model_dump())
    session.add(site)
    await session.commit()
    await session.refresh(site)
    return site


@router.patch("/{site_id}", response_model=SiteOut)
async def update_site(
    site_id: int,
    data: SiteUpdate,
    session: AsyncSession = Depends(get_session),
):
    site = await session.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Site not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(site, field, value)
    await session.commit()
    await session.refresh(site)
    return site


@router.delete("/{site_id}", status_code=204)
async def delete_site(site_id: int, session: AsyncSession = Depends(get_session)):
    site = await session.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Site not found")
    await session.delete(site)
    await session.commit()
