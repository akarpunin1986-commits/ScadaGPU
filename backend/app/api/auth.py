"""ScadaGPU — Auth API router (/api/auth)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from config import settings
from middleware.auth import get_current_user, require_role
from models.base import async_session
from models.scada_user import ScadaUser, UserRole
from models.user_activity import UserActivity
from services import auth

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class RequestCodeBody(BaseModel):
    email: str


class VerifyCodeBody(BaseModel):
    email: str
    code: str


class VerifyCodeResponse(BaseModel):
    status: str
    user: dict


class MeResponse(BaseModel):
    id: int
    name: str
    email: str | None
    role: str
    avatar_url: str | None
    department: str | None
    position: str | None
    hierarchy_level: int
    bitrix_id: int


class UserListItem(BaseModel):
    id: int
    name: str
    email: str | None
    role: str
    is_active: bool
    department: str | None
    position: str | None
    last_login: datetime | None


class UpdateRoleBody(BaseModel):
    role: str


class UpdateActiveBody(BaseModel):
    is_active: bool


class StatusResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/request-code")
async def request_code(body: RequestCodeBody, request: Request):
    """Send an auth code to the given email."""
    try:
        redis = request.app.state.redis
        result = await auth.request_code(body.email, redis)
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/verify-code", response_model=VerifyCodeResponse)
async def verify_code(body: VerifyCodeBody, response: Response):
    """Verify an auth code and set JWT cookie."""
    try:
        result = await auth.verify_code(body.email, body.code)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    token = result.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Verification failed")

    max_age = 365 * 86400 if settings.JWT_EXPIRE_HOURS == 0 else settings.JWT_EXPIRE_HOURS * 3600
    response.set_cookie(
        key="scada_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=max_age,
        path="/",
    )

    user_data = result.get("user", {})
    return {
        "status": "ok",
        "user": {
            "name": user_data.get("name"),
            "role": user_data.get("role"),
            "avatar_url": user_data.get("avatar_url"),
        },
    }


@router.get("/me", response_model=MeResponse)
async def me(user: ScadaUser = Depends(get_current_user)):
    """Return current authenticated user info."""
    return MeResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        role=user.role,
        avatar_url=user.avatar_url,
        department=user.department,
        position=user.position,
        hierarchy_level=user.hierarchy_level,
        bitrix_id=user.bitrix_id,
    )


@router.post("/logout", response_model=StatusResponse)
async def logout(response: Response):
    """Clear auth cookie."""
    response.delete_cookie(key="scada_token", path="/")
    return {"status": "ok"}


@router.get("/users", response_model=list[UserListItem])
async def list_users(user: ScadaUser = Depends(require_role("admin"))):
    """List all users (admin only)."""
    async with async_session() as session:
        result = await session.execute(select(ScadaUser))
        users = result.scalars().all()

    return [
        UserListItem(
            id=u.id,
            name=u.name,
            email=u.email,
            role=u.role,
            is_active=u.is_active,
            department=u.department,
            position=u.position,
            last_login=u.last_login,
        )
        for u in users
    ]


@router.put("/users/{user_id}/role", response_model=StatusResponse)
async def update_user_role(
    user_id: int,
    body: UpdateRoleBody,
    admin: ScadaUser = Depends(require_role("admin")),
):
    """Change a user's role (admin only)."""
    try:
        UserRole(body.role)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Allowed: {[r.value for r in UserRole]}",
        )

    if user_id == admin.id:
        raise HTTPException(400, "Нельзя изменить свою роль")

    async with async_session() as session:
        result = await session.execute(
            select(ScadaUser).where(ScadaUser.id == user_id)
        )
        target = result.scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")

        old_role = target.role
        target.role = body.role

        activity = UserActivity(
            user_id=admin.id,
            action="user_role_change",
            details={
                "target_user_id": user_id,
                "old_role": old_role,
                "new_role": body.role,
            },
        )
        session.add(activity)
        await session.commit()

    return {"status": "ok"}


@router.put("/users/{user_id}/active", response_model=StatusResponse)
async def update_user_active(
    user_id: int,
    body: UpdateActiveBody,
    admin: ScadaUser = Depends(require_role("admin")),
):
    """Activate or deactivate a user (admin only)."""
    if user_id == admin.id:
        raise HTTPException(400, "Нельзя деактивировать себя")

    async with async_session() as session:
        result = await session.execute(
            select(ScadaUser).where(ScadaUser.id == user_id)
        )
        target = result.scalar_one_or_none()
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")

        target.is_active = body.is_active

        activity = UserActivity(
            user_id=admin.id,
            action="user_active_change",
            details={"target_user_id": user_id, "is_active": body.is_active},
        )
        session.add(activity)
        await session.commit()

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Admin: company sync
# ---------------------------------------------------------------------------

@router.post("/admin/sync-company")
async def force_sync_company(request: Request, user: ScadaUser = Depends(require_role("admin"))):
    """Force company structure sync from B24. Admin only."""
    from services.company_sync import sync_company_structure
    redis = request.app.state.redis
    result = await sync_company_structure(redis)
    last = await redis.get("company:last_sync")
    return {"status": "ok", **result, "last_sync": last.decode() if last else None}


# ---------------------------------------------------------------------------
# OAuth автовход
# ---------------------------------------------------------------------------

import json
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from fastapi.responses import HTMLResponse, JSONResponse

OAUTH_STATE_TTL = 300  # 5 мин на авторизацию
QR_TTL = 180  # 3 мин на QR-сессию


async def _oauth_exchange_and_login(code: str, redirect_uri: str, request: Request):
    """Exchange OAuth code → access_token → B24 user → scada_user → JWT."""
    import httpx as _httpx

    async with _httpx.AsyncClient(timeout=10) as client:
        resp = await client.post("https://oauth.bitrix.info/oauth/token/", data={
            "grant_type": "authorization_code",
            "client_id": settings.BITRIX24_OAUTH_CLIENT_ID,
            "client_secret": settings.BITRIX24_OAUTH_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
        })
    tokens = resp.json()
    if "error" in tokens:
        raise HTTPException(400, f"OAuth: {tokens.get('error_description', tokens['error'])}")

    b24_user = await auth.get_bitrix_user_oauth(tokens["access_token"])
    if not b24_user.get("ID"):
        raise HTTPException(400, "Не удалось получить данные из Б24")

    redis = getattr(request.app.state, 'redis', None) if request else None
    async with async_session() as session:
        user = await auth.sync_user_from_bitrix(session, b24_user, redis=redis)
        if not user.is_active:
            raise HTTPException(403, "Учётная запись деактивирована")
        user.bitrix_access_token = tokens.get("access_token")
        user.bitrix_refresh_token = tokens.get("refresh_token")
        await session.commit()
        await session.refresh(user)

    return user, auth.create_jwt(user)


@router.get("/oauth/login")
async def oauth_login(request: Request):
    """Redirect юзера на Б24 OAuth."""
    state = secrets.token_hex(16)
    redis = request.app.state.redis
    await redis.set(f"oauth:state:{state}", "1", ex=OAUTH_STATE_TTL)

    params = {
        "client_id": settings.BITRIX24_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.BITRIX24_OAUTH_REDIRECT_URI,
        "state": state,
    }
    url = f"https://{settings.BITRIX24_PORTAL}/oauth/authorize/?" + urlencode(params)
    return RedirectResponse(url)


@router.get("/oauth/callback")
async def oauth_callback(code: str, state: str, request: Request, domain: str = ""):
    """Б24 redirect с code → JWT → cookie → redirect /."""
    redis = request.app.state.redis

    # CSRF check
    stored = await redis.get(f"oauth:state:{state}")
    if not stored:
        raise HTTPException(400, "Invalid or expired state")
    await redis.delete(f"oauth:state:{state}")

    user, jwt_token = await _oauth_exchange_and_login(
        code, settings.BITRIX24_OAUTH_REDIRECT_URI, request)

    try:
        from services.activity_logger import log_activity
        await log_activity(user.id, "auth_login_oauth", source="scada",
                         details={"method": "oauth", "bitrix_id": user.bitrix_id})
    except Exception:
        pass

    # Cookie on LAN domain — use HTML meta-refresh instead of 307
    # (307 + Set-Cookie can be blocked by browsers in cross-site redirect chains)
    from fastapi.responses import HTMLResponse
    max_age = 365 * 86400 if settings.JWT_EXPIRE_HOURS == 0 else settings.JWT_EXPIRE_HOURS * 3600
    resp = HTMLResponse(
        content='<html><head><meta http-equiv="refresh" content="0;url=http://192.168.30.130/"></head><body>OK</body></html>',
        status_code=200,
    )
    resp.set_cookie(key="scada_token", value=jwt_token, httponly=True,
                    samesite="lax", max_age=max_age, path="/",
)
    return resp


@router.get("/oauth/set-token")
async def oauth_set_token(t: str):
    """Set JWT cookie on LAN domain after OAuth redirect from external IP."""
    # Validate JWT before setting cookie (prevent session fixation)
    payload = auth.verify_jwt(t)
    if not payload:
        raise HTTPException(400, "Invalid or expired token")
    from fastapi.responses import HTMLResponse
    max_age = 365 * 86400 if settings.JWT_EXPIRE_HOURS == 0 else settings.JWT_EXPIRE_HOURS * 3600
    resp = HTMLResponse(
        content='<html><head><meta http-equiv="refresh" content="0;url=http://192.168.30.130/"></head><body>OK</body></html>',
        status_code=200,
    )
    resp.set_cookie(key="scada_token", value=t, httponly=True,
                    samesite="lax", max_age=max_age, path="/",
)
    return resp


# ---------------------------------------------------------------------------
# QR-вход через OAuth
# ---------------------------------------------------------------------------

@router.post("/qr/create")
async def qr_create(request: Request):
    """Создать QR-сессию."""
    redis = request.app.state.redis
    token = secrets.token_hex(32)
    await redis.set(f"qr:{token}", json.dumps({"status": "pending"}), ex=QR_TTL)

    # QR URL через внешний адрес (чтобы работал с 4G телефона)
    qr_url = f"https://85.234.9.55:8443/api/auth/qr/page?t={token}"
    expires_at = (datetime.utcnow() + timedelta(seconds=QR_TTL)).isoformat()
    return {"session_token": token, "qr_url": qr_url, "expires_at": expires_at}


@router.get("/qr/status")
async def qr_status(token: str, request: Request):
    """Polling статуса QR-сессии (десктоп)."""
    redis = request.app.state.redis
    data = await redis.get(f"qr:{token}")
    if not data:
        return {"status": "expired"}

    session_data = json.loads(data)

    if session_data["status"] == "ready":
        await redis.delete(f"qr:{token}")
        response = JSONResponse({"status": "ready", "user_name": session_data.get("user_name")})
        max_age = 365 * 86400 if settings.JWT_EXPIRE_HOURS == 0 else settings.JWT_EXPIRE_HOURS * 3600
        response.set_cookie(key="scada_token", value=session_data["jwt"],
                            httponly=True, samesite="lax", max_age=max_age, path="/",
        )
        return response

    return {"status": session_data["status"]}


@router.get("/qr/oauth-start")
async def qr_oauth_start(t: str):
    """Redirect телефона на Б24 OAuth. state = session_token."""
    params = {
        "client_id": settings.BITRIX24_OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.BITRIX24_QR_OAUTH_REDIRECT_URI,
        "state": t,
    }
    url = f"https://{settings.BITRIX24_PORTAL}/oauth/authorize/?" + urlencode(params)
    return RedirectResponse(url)


@router.get("/qr/oauth-callback")
async def qr_oauth_callback(code: str, state: str, request: Request, domain: str = ""):
    """OAuth callback с телефона. state = session_token QR-сессии."""
    redis = request.app.state.redis
    session_token = state

    # Проверить QR-сессию
    data = await redis.get(f"qr:{session_token}")
    if not data:
        return HTMLResponse(
            '<div style="text-align:center;padding:40px;font-family:sans-serif;">'
            '<h2>❌ QR-код истёк</h2><p>Откройте СКАДУ и получите новый.</p></div>'
        )
    session_data = json.loads(data)
    if session_data["status"] != "pending":
        return HTMLResponse(
            '<div style="text-align:center;padding:40px;font-family:sans-serif;">'
            '<h2>❌ QR-код уже использован</h2></div>'
        )

    try:
        user, jwt_token = await _oauth_exchange_and_login(
            code, settings.BITRIX24_QR_OAUTH_REDIRECT_URI, request)
    except HTTPException as e:
        return HTMLResponse(
            f'<div style="text-align:center;padding:40px;font-family:sans-serif;">'
            f'<h2>❌ Ошибка: {e.detail}</h2></div>'
        )

    # Обновить QR-сессию — десктоп подхватит при polling
    await redis.set(f"qr:{session_token}", json.dumps({
        "status": "ready",
        "jwt": jwt_token,
        "user_name": user.name,
    }), ex=60)

    # Уведомить в Б24
    try:
        from services.bitrix_bot import b24_app_call
        await b24_app_call("imbot.message.add", {
            "BOT_ID": settings.BITRIX24_BOT_ID,
            "DIALOG_ID": str(user.bitrix_id),
            "MESSAGE": "✅ Вы вошли в ScadaGPU с другого устройства.",
        }, redis=redis)
    except Exception:
        pass

    return HTMLResponse(
        '<div style="text-align:center;padding:40px;font-family:sans-serif;">'
        '<h2 style="color:#2e7d32">✅ Вход подтверждён!</h2>'
        '<p>Можете закрыть эту страницу.</p></div>'
    )


# Мобильная страница для QR
@router.get("/qr/page")
async def qr_page(t: str):
    """Мобильная HTML-страница: кнопка 'Войти через Б24'."""
    return HTMLResponse(f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ScadaGPU — Вход</title>
<style>
body{{margin:0;padding:40px 20px;font-family:-apple-system,sans-serif;
background:#06090f;color:#e8edf5;text-align:center}}
h2{{font-size:20px;margin-bottom:8px}}
p{{color:#94a3b8;font-size:14px;margin-bottom:32px}}
a.btn{{display:inline-block;padding:14px 32px;background:#00e09a;color:#080c14;
border-radius:10px;text-decoration:none;font-size:16px;font-weight:600}}
a.btn:active{{opacity:.8}}
.logo{{font-size:28px;margin-bottom:16px}}
</style></head><body>
<div class="logo">⚡</div>
<h2>ScadaGPU — Вход</h2>
<p>Вы входите в СКАДУ на другом устройстве</p>
<a class="btn" href="/api/auth/qr/oauth-start?t={t}">Войти через Битрикс24</a>
</body></html>''')
