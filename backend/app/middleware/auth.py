"""ScadaGPU — JWT auth middleware for FastAPI."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from models.base import async_session
from models.scada_user import ScadaUser
from services.auth import verify_jwt


async def get_current_user(request: Request) -> ScadaUser:
    """Extract and validate JWT from cookie, return active ScadaUser."""
    token = request.cookies.get("scada_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = verify_jwt(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    async with async_session() as session:
        result = await session.execute(
            select(ScadaUser).where(ScadaUser.id == int(payload["sub"]))
        )
        user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")

    return user


async def get_optional_user(request: Request) -> ScadaUser | None:
    """Same as get_current_user but returns None instead of raising."""
    token = request.cookies.get("scada_token")
    if not token:
        return None

    payload = verify_jwt(token)
    if payload is None:
        return None

    async with async_session() as session:
        result = await session.execute(
            select(ScadaUser).where(ScadaUser.id == int(payload["sub"]))
        )
        user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        return None

    return user


def require_role(*roles: str):
    """Return a FastAPI dependency that enforces role membership."""

    async def _check_role(user: ScadaUser = Depends(get_current_user)) -> ScadaUser:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return _check_role
