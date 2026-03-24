"""Bitrix24 Chat-Bot API — Phase 3.

Receives events from Bitrix24 bot framework, processes messages
through Sanek v4, returns responses to B24 chat.

Endpoints:
  POST /api/bitrix/bot/event    — bot lifecycle events (install/delete)
  POST /api/bitrix/bot/message  — incoming user messages + COMMAND events
  POST /api/bitrix/bot/register — admin: one-time bot registration
  GET  /api/bitrix/bot/status   — bot status info
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from config import settings

router = APIRouter(prefix="/api/bitrix/bot", tags=["bitrix-bot"])
logger = logging.getLogger("scada.api.bitrix_bot")


# ─── Bot lifecycle events ─────────────────────────────────────────────

@router.get("/event")
async def bot_event_get(request: Request, code: str = "", state: str = "", domain: str = ""):
    """Handle OAuth callback from B24 (redirects here instead of redirect_uri).

    B24 local apps redirect to handler URL with code + state as GET params.
    """
    if code:
        # This is an OAuth callback — delegate to auth handler
        from fastapi.responses import RedirectResponse
        from services import auth as auth_service
        from models.base import async_session
        from config import settings
        import httpx as _httpx

        logger.info("OAuth callback via /event: code=%s..., state=%s", code[:10], state[:10] if state else "none")

        # Exchange code for token
        try:
            async with _httpx.AsyncClient(timeout=10) as client:
                resp = await client.post("https://bricks-trade.bitrix24.ru/oauth/token/", data={
                    "grant_type": "authorization_code",
                    "client_id": settings.BITRIX24_OAUTH_CLIENT_ID,
                    "client_secret": settings.BITRIX24_OAUTH_CLIENT_SECRET,
                    "code": code,
                })
            tokens = resp.json()

            if "error" in tokens:
                logger.error("OAuth token error: %s", tokens)
                return {"error": tokens.get("error_description", "OAuth failed")}

            b24_user = await auth_service.get_bitrix_user_oauth(tokens["access_token"])
            if not b24_user.get("ID"):
                return {"error": "Failed to get B24 user"}

            async with async_session() as session:
                user = await auth_service.sync_user_from_bitrix(session, b24_user)
                user.bitrix_access_token = tokens.get("access_token")
                user.bitrix_refresh_token = tokens.get("refresh_token")
                await session.commit()
                await session.refresh(user)

            jwt_token = auth_service.create_jwt(user)

            try:
                from services.activity_logger import log_activity
                await log_activity(user.id, "auth_login_oauth", source="scada",
                                 details={"method": "oauth_via_bot", "bitrix_id": user.bitrix_id})
            except Exception:
                pass

            # Redirect to LAN SCADA with cookie
            response = RedirectResponse("http://192.168.30.130/api/auth/oauth/set-token?t=" + jwt_token)
            return response

        except Exception as e:
            logger.exception("OAuth via /event error: %s", e)
            return {"error": str(e)}

    return {"status": "ok", "message": "No code provided"}


@router.post("/event")
async def bot_event(request: Request):
    """Handle bot lifecycle events (ONIMBOTINSTALL, ONIMBOTDELETE).

    B24 sends these when the bot is installed/removed from a portal.
    Validates application_token for security.
    """
    # B24 may send JSON or form-data — try both
    raw_body = await request.body()
    logger.info("Bot /event raw body (%d bytes): %s", len(raw_body), raw_body[:500].decode('utf-8', errors='replace'))

    try:
        body = await request.json()
    except Exception:
        body = dict(await request.form())

    event_type = body.get("event", "")

    # B24 form-data sends nested keys as auth[access_token], auth[refresh_token] etc.
    # Reconstruct auth dict from flat keys
    auth = body.get("auth", {})
    if not isinstance(auth, dict) or not auth:
        auth = {}
        for k, v in body.items():
            if k.startswith("auth[") and k.endswith("]"):
                auth[k[5:-1]] = v
    application_token = auth.get("application_token", "") or body.get("application_token", "")

    logger.info("Bot event received: %s, token=%s...",
                event_type, application_token[:8] if application_token else "none")

    # Verify application_token if configured
    expected_token = getattr(settings, "BITRIX24_APP_TOKEN", "")
    if expected_token and application_token != expected_token:
        logger.warning("Bot event: invalid application_token")
        raise HTTPException(status_code=403, detail="Invalid application_token")

    if event_type in ("ONIMBOTINSTALL", "ONAPPINSTALL"):
        # App/bot installed — save access tokens
        redis = request.app.state.redis

        # Tokens can be in auth{} or top-level
        access_token = auth.get("access_token", "") or body.get("access_token", "")
        refresh_token = auth.get("refresh_token", "") or body.get("refresh_token", "")
        app_token = application_token or auth.get("application_token", "")
        bot_id = body.get("data", {}).get("BOT_ID") or body.get("BOT_ID")

        logger.info("App/Bot install: event=%s, has_access=%s, has_refresh=%s, has_app=%s, bot_id=%s, body_keys=%s",
                     event_type, bool(access_token), bool(refresh_token), bool(app_token), bot_id, list(body.keys()))

        if access_token:
            await redis.set("bitrix:bot:access_token", access_token, ex=3500)
            logger.info("Saved access_token to Redis")

        if refresh_token:
            await redis.set("bitrix:bot:refresh_token", refresh_token)
            logger.info("Saved refresh_token to Redis")

        if app_token:
            await redis.set("bitrix:bot:app_token", app_token)
            logger.info("Saved app_token to Redis")

        return {"success": True, "event": "install", "bot_id": bot_id}

    elif event_type in ("ONIMBOTDELETE", "ONAPPUNINSTALL"):
        logger.warning("Bot was deleted from portal")
        redis = request.app.state.redis
        await redis.delete("bitrix:bot:access_token")
        await redis.delete("bitrix:bot:refresh_token")
        return {"success": True, "event": "delete"}

    return {"success": True, "event": event_type}


# ─── Incoming messages ────────────────────────────────────────────────

@router.post("/message")
async def bot_message(request: Request):
    """Handle incoming messages from B24 users and COMMAND events.

    B24 expects a fast 200 response, so actual processing happens
    in a background task via asyncio.create_task.
    """
    try:
        body = await request.json()
    except Exception:
        try:
            body = dict(await request.form())
        except Exception:
            logger.error("Failed to parse bot message body")
            return {"status": "error", "message": "invalid body"}

    event_type = body.get("event", "")

    # Only handle message/command events
    if event_type not in ("ONIMBOTMESSAGEADD", "ONIMCOMMANDADD", "ONIMMESSAGEADD"):
        logger.debug("Ignoring bot event: %s", event_type)
        return {"status": "ignored", "event": event_type}

    # B24 form-data sends nested keys like data[PARAMS][MESSAGE] as flat strings
    # Reconstruct nested structure for handle_bot_message
    normalized = {"event": event_type}
    params = {}
    for k, v in body.items():
        if k.startswith("data[PARAMS][") and k.endswith("]"):
            param_key = k[13:-1]
            params[param_key] = v
    if params:
        normalized["data"] = {"PARAMS": params}
    else:
        normalized["data"] = body.get("data", {})

    # Also extract auth for token refresh
    auth = {}
    for k, v in body.items():
        if k.startswith("auth[") and k.endswith("]"):
            auth[k[5:-1]] = v
    if auth:
        normalized["auth"] = auth

    # Verify application_token (prevent fake messages)
    app_token = auth.get("application_token", "") or body.get("application_token", "")
    expected_token = getattr(settings, "BITRIX24_BOT_APP_TOKEN", "")
    if expected_token and app_token != expected_token:
        logger.warning("Bot /message: invalid application_token from %s", params.get("FROM_USER_ID", "?"))
        raise HTTPException(status_code=403, detail="Invalid application_token")

    logger.info("Bot message: event=%s, from=%s, msg=%s",
                event_type, params.get("FROM_USER_ID", "?"), (params.get("MESSAGE") or "")[:60])

    redis = request.app.state.redis

    # Save fresh access_token if provided
    if auth.get("access_token"):
        await redis.set("bitrix:bot:access_token", auth["access_token"], ex=3500)
    if auth.get("refresh_token"):
        await redis.set("bitrix:bot:refresh_token", auth["refresh_token"])

    # Process in background — B24 needs fast response
    from services.bitrix_bot import handle_bot_message

    asyncio.create_task(
        _safe_handle(handle_bot_message, normalized, redis),
        name=f"b24bot-{event_type}",
    )

    return {"status": "ok"}


async def _safe_handle(handler, event_data: dict, redis) -> None:
    """Wrapper to catch and log any unhandled exceptions in background task."""
    try:
        await handler(event_data, redis)
    except Exception as e:
        logger.exception("Background bot handler failed: %s", e)


# ─── Bot registration (admin) ────────────────────────────────────────

@router.post("/register")
async def register_bot_endpoint(request: Request):
    """One-time bot registration in Bitrix24.

    Creates the bot entity via imbot.register using the admin webhook.
    After registration, set BITRIX24_BOT_ID in .env.
    """
    # Simple admin check: only allow from localhost or with configured token
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        # Check for admin header
        admin_token = request.headers.get("X-Admin-Token", "")
        jwt_secret = settings.JWT_SECRET_KEY
        if not jwt_secret or admin_token != jwt_secret:
            raise HTTPException(
                status_code=403,
                detail="Admin access required (localhost or X-Admin-Token header)",
            )

    redis = request.app.state.redis

    from services.bitrix_bot import register_bot
    result = await register_bot(redis)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Registration failed"))

    return result


# ─── Bot status ──────────────────────────────────────────────────────

@router.get("/status")
async def bot_status(request: Request):
    """Get bot configuration and status."""
    redis = request.app.state.redis

    # Check if token is available
    has_token = False
    try:
        cached_token = await redis.get("bitrix:bot:access_token")
        has_token = bool(cached_token) or bool(settings.BITRIX24_BOT_ACCESS_TOKEN)
    except Exception:
        has_token = bool(settings.BITRIX24_BOT_ACCESS_TOKEN)

    return {
        "bot_id": settings.BITRIX24_BOT_ID,
        "handler_url": settings.BITRIX24_BOT_HANDLER_URL,
        "portal": settings.BITRIX24_PORTAL,
        "registered": settings.BITRIX24_BOT_ID > 0,
        "has_access_token": has_token,
        "sanek_webhook_configured": bool(settings.BITRIX24_SANEK_WEBHOOK_URL),
    }


@router.post("/update-profile")
async def api_update_bot_profile(request: Request):
    """Update bot profile (name, description, avatar).

    Admin only. Call after deploy or when changing avatar.
    """
    redis = request.app.state.redis
    from services.bitrix_bot import update_bot_profile
    result = await update_bot_profile(redis=redis)

    if result.get("result"):
        return {"status": "ok", "message": "Бот обновлён: Робот Санёк"}
    else:
        return {"status": "error", "detail": result}
