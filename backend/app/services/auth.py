"""ScadaGPU — AuthService: code-based login via Bitrix24 notifications."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

import httpx
import jwt
from sqlalchemy import and_, select

from config import settings
from models.auth_code import AuthCode
from models.base import async_session
from models.scada_user import ScadaUser
from services.hierarchy import (
    auto_role_from_hierarchy,
    calc_hierarchy_level,
    calc_user_weight,
    resolve_default_role,
)

logger = logging.getLogger("scada.auth")

AUTH_CODE_MARKER = "[auth-code]"


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

async def request_code(email: str, redis) -> dict:
    """Generate a 6-digit auth code and send it via Bitrix24 IM notification.

    Returns a dict with ``status`` or ``error`` key.
    """
    email = email.strip().lower()

    # 1. Rate limit
    rate_key = f"auth:rate:{email}"
    if not await redis.set(rate_key, "1", ex=settings.AUTH_CODE_RATE_LIMIT_SECONDS, nx=True):
        return {"error": "rate_limit", "message": "Подождите минуту"}

    # 2. Search user in Bitrix24 (via app access_token)
    try:
        from services.bitrix_bot import b24_app_call
        b24_data = await b24_app_call("user.search", {"EMAIL": email}, redis=redis)
        if "error" in b24_data:
            logger.error("Bitrix24 user.search error: %s", b24_data)
            return {"error": "bitrix_error", "message": "Ошибка связи с Битрикс24"}
    except Exception as exc:
        logger.error("Bitrix24 user.search failed: %s", exc)
        return {"error": "bitrix_error", "message": "Ошибка связи с Битрикс24"}

    results = b24_data.get("result", [])
    if not results:
        return {"error": "not_found", "message": "Email не найден в Битрикс24"}

    b24_user = results[0]
    bitrix_id = int(b24_user.get("ID", 0))

    # 3-6. Find or create ScadaUser, sync fields, calculate hierarchy
    async with async_session() as session:
        user = await sync_user_from_bitrix(session, b24_user, redis=redis)
        await session.commit()
        await session.refresh(user)

        # 7. Generate code
        code = str(secrets.randbelow(900000) + 100000)

        # 8. Save AuthCode
        auth_code = AuthCode(
            user_id=user.id,
            code=code,
            expires_at=datetime.utcnow() + timedelta(seconds=settings.AUTH_CODE_TTL_SECONDS),
        )
        session.add(auth_code)
        await session.commit()

    # 9. Send code via bot 226 (imbot.message.add)
    try:
        from services.bitrix_bot import b24_app_call
        await b24_app_call("imbot.message.add", {
            "BOT_ID": settings.BITRIX24_BOT_ID,
            "DIALOG_ID": str(bitrix_id),
            "MESSAGE": f"{AUTH_CODE_MARKER}🔐 Код входа в ScadaGPU: [b]{code}[/b]\n\nДействует 5 минут.",
        }, redis=redis)
    except Exception as exc:
        logger.error("imbot.message.add failed for bitrix_id=%s: %s", bitrix_id, exc)
        # Code is already saved — user can still try, we just log the error

    # 10. Return success
    return {"status": "code_sent", "user_name": user.name}


async def verify_code(email: str, code: str) -> dict:
    """Verify an auth code submitted by the user.

    Returns JWT on success or an error dict.
    """
    email = email.strip().lower()

    async with async_session() as session:
        # 1. Find user
        stmt = select(ScadaUser).where(ScadaUser.email == email)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            return {"error": "invalid_code"}

        # 2. Find latest unused, non-expired code
        now = datetime.utcnow()
        stmt = (
            select(AuthCode)
            .where(
                and_(
                    AuthCode.user_id == user.id,
                    AuthCode.is_used.is_(False),
                    AuthCode.expires_at > now,
                )
            )
            .order_by(AuthCode.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        auth_code = result.scalar_one_or_none()

        if not auth_code:
            return {"error": "invalid_code"}

        # 3. Max attempts check
        if auth_code.attempts >= settings.AUTH_MAX_ATTEMPTS:
            auth_code.is_used = True
            await session.commit()
            return {"error": "max_attempts"}

        # 4. Code comparison
        if auth_code.code == code:
            auth_code.is_used = True
            user.last_login = now
            await session.commit()
            token = create_jwt(user)
            # Log activity
            try:
                from services.activity_logger import log_activity
                await log_activity(user.id, "auth_login_code", source="scada",
                                 details={"email": email, "method": "code"})
            except Exception:
                pass
            return {
                "status": "ok",
                "token": token,
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "role": user.role,
                    "avatar_url": user.avatar_url,
                },
            }

        # 5. Wrong code — increment attempts
        auth_code.attempts += 1
        await session.commit()
        attempts_left = settings.AUTH_MAX_ATTEMPTS - auth_code.attempts
        return {"error": "wrong_code", "attempts_left": attempts_left}


# ------------------------------------------------------------------
# JWT helpers
# ------------------------------------------------------------------

def create_jwt(user: ScadaUser) -> str:
    """Create a signed JWT for the given user."""
    payload: dict = {
        "sub": str(user.id),
        "role": user.role,
        "name": user.name,
        "bid": user.bitrix_id,
    }
    if settings.JWT_EXPIRE_HOURS > 0:
        payload["exp"] = datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_jwt(token: str) -> dict | None:
    """Decode and verify a JWT. Returns the payload dict or ``None``."""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except Exception as e:
        logging.getLogger("scada.auth").debug("JWT verify failed: %s", e)
        return None


# ------------------------------------------------------------------
# Bitrix24 user sync
# ------------------------------------------------------------------

async def sync_user_from_bitrix(
    session,
    bitrix_user_data: dict,
    dept_data: dict | None = None,
    redis=None,
) -> ScadaUser:
    """Create or update a ScadaUser from raw Bitrix24 ``user.search`` data.

    *dept_data* is an optional dict with extra department info (unused for
    now but reserved for Phase 2 department tree sync).
    """
    bitrix_id = int(bitrix_user_data.get("ID", 0))
    last_name = bitrix_user_data.get("LAST_NAME", "")
    first_name = bitrix_user_data.get("NAME", "")
    name = f"{last_name} {first_name}".strip() or f"User {bitrix_id}"
    email = (bitrix_user_data.get("EMAIL") or "").strip().lower() or None
    position = bitrix_user_data.get("WORK_POSITION") or ""
    is_head = bool(bitrix_user_data.get("UF_DEPARTMENT_HEAD"))
    avatar = bitrix_user_data.get("PERSONAL_PHOTO") or None
    manager_id = int(bitrix_user_data["UF_MANAGER"]) if bitrix_user_data.get("UF_MANAGER") else None

    # Department — B24 returns list of IDs; take the first one
    dept_ids = bitrix_user_data.get("UF_DEPARTMENT", [])
    department_id = int(dept_ids[0]) if dept_ids else None

    # Try to get department name from B24
    department_name = None
    if department_id:
        try:
            from services.bitrix_bot import b24_app_call
            dept_resp = await b24_app_call("department.get", {"ID": department_id}, redis=redis)
            dept_list = dept_resp.get("result", [])
            if dept_list:
                department_name = dept_list[0].get("NAME", "")
        except Exception as e:
            logger.debug("department.get failed for %s: %s", department_id, e)

    # Hierarchy
    hierarchy_level = calc_hierarchy_level(position, is_head)
    user_weight = calc_user_weight(hierarchy_level)

    # Find existing user
    stmt = select(ScadaUser).where(ScadaUser.bitrix_id == bitrix_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        # Resolve default role for new users
        default_role = await resolve_default_role(session, department_id, hierarchy_level)

        user = ScadaUser(
            bitrix_id=bitrix_id,
            name=name,
            email=email,
            position=position,
            is_department_head=is_head,
            department_id=department_id,
            department=department_name,
            avatar_url=avatar,
            manager_bitrix_id=manager_id,
            hierarchy_level=hierarchy_level,
            user_weight=user_weight,
            role=default_role,
        )
        session.add(user)
    else:
        # Sync mutable fields (role is NOT overwritten — admin can change it)
        user.name = name
        user.email = email
        user.position = position
        user.is_department_head = is_head
        user.department_id = department_id
        if department_name:
            user.department = department_name
        user.avatar_url = avatar
        user.manager_bitrix_id = manager_id
        user.hierarchy_level = hierarchy_level
        user.user_weight = user_weight

    return user


# ------------------------------------------------------------------
# OAuth (Phase 2 — skeleton, waiting for partner account)
# ------------------------------------------------------------------

def get_oauth_url() -> str:
    """Build Bitrix24 OAuth authorization URL."""
    from urllib.parse import urlencode

    return f"https://{settings.BITRIX24_PORTAL}/oauth/authorize/?" + urlencode({
        "client_id": settings.BITRIX24_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.BITRIX24_OAUTH_REDIRECT_URI,
    })


async def exchange_oauth_code(code: str) -> dict:
    """Exchange OAuth authorization code for access + refresh tokens."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post("https://oauth.bitrix.info/oauth/token/", data={
            "grant_type": "authorization_code",
            "client_id": settings.BITRIX24_OAUTH_CLIENT_ID,
            "client_secret": settings.BITRIX24_OAUTH_CLIENT_SECRET,
            "redirect_uri": settings.BITRIX24_OAUTH_REDIRECT_URI,
            "code": code,
        })
    return resp.json()


async def get_bitrix_user_oauth(access_token: str) -> dict:
    """Fetch current user info using OAuth access_token."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"https://{settings.BITRIX24_PORTAL}/rest/user.current",
            params={"auth": access_token},
        )
    return resp.json().get("result", {})
