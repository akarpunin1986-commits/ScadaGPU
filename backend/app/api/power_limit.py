"""Power Limit API — read/write generator power limit settings (P%, Q%, LoadMode).

Supports both HGM9520N (generators) and HGM9560 (SPR/ATS):
- HGM9520N: read regs 159-162 (live from Redis), write regs 4368 (P%) + 4370 (Q%)
- HGM9560:  read regs 4351-4354 (LoadMode + P% + Q%), write same via FC06
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/devices", tags=["power-limit"])

logger = logging.getLogger("scada.power_limit")

LOAD_MODE_TEXT = {0: "Gen Control", 1: "Mains Control", 2: "Load Reception"}


def _signed16(val: int) -> int:
    """Convert unsigned 16-bit to signed (matches poller's _signed16)."""
    return val - 65536 if val > 32767 else val


# --- Models ---

class PowerLimitResponse(BaseModel):
    success: bool
    message: str
    device_id: int
    device_type: str
    current_p_pct: float | None = None
    target_p_pct: float | None = None
    current_q_pct: float | None = None
    target_q_pct: float | None = None
    config_p_raw: int | None = None
    config_q_raw: int | None = None
    load_mode: int | None = None
    load_mode_text: str | None = None
    power_limit_active: bool | None = None
    power_limit_trip: bool | None = None


class PowerLimitWriteRequest(BaseModel):
    p_raw: int        # P% × 10 (0-1000 → 0.0-100.0%)
    q_raw: int        # Q% × 10 (0-1000 → 0.0-100.0%)
    load_mode: int | None = None  # 0/1/2 — only for HGM9560 (SPR)


class PowerLimitWriteResponse(BaseModel):
    success: bool
    message: str
    device_id: int
    device_type: str
    p_raw: int
    q_raw: int
    load_mode: int | None = None
    verified: bool
    verify_values: dict | None = None


# --- Helpers ---

def _get_reader(request: Request, device_id: int):
    """Get poller reader for device, raise HTTP errors if not found."""
    poller = getattr(request.app.state, "poller", None)
    if poller is None:
        raise HTTPException(503, "Poller not initialized")
    readers = getattr(poller, "_readers", {})
    reader = readers.get(device_id)
    if reader is None:
        raise HTTPException(404, f"Device {device_id} not found in active readers")
    return reader


def _get_device_type(reader) -> str:
    """Extract device type string from reader."""
    dt = getattr(reader, "device", None)
    if dt and hasattr(dt, "device_type"):
        return dt.device_type.value if hasattr(dt.device_type, "value") else str(dt.device_type)
    # Fallback: check class name
    cls_name = type(reader).__name__
    if "9520" in cls_name:
        return "generator"
    if "9560" in cls_name:
        return "ats"
    return "unknown"


async def _get_redis_metrics(request: Request, device_id: int) -> dict:
    """Read latest metrics from Redis for a device."""
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return {}
    raw = await redis.get(f"device:{device_id}:metrics")
    if not raw:
        return {}
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


# --- GET endpoint ---

@router.get("/{device_id}/power-limit", response_model=PowerLimitResponse)
async def get_power_limit(device_id: int, request: Request):
    """Read current power limit configuration for a device."""

    reader = _get_reader(request, device_id)
    device_type = _get_device_type(reader)
    mx = await _get_redis_metrics(request, device_id)

    if device_type == "generator":
        # HGM9520N: read regs 159-162 directly from controller via FC03.
        # Regs: 159=current_p, 160=target_p, 161=current_q, 162=target_q
        # These are always readable (unlike config regs 4368/4370 which are write-only).
        # Direct read works even in standby (when poller skips gen_volt_plimit).
        current_p = None
        target_p = None
        current_q = None
        target_q = None
        config_p_raw = None
        config_q_raw = None

        try:
            batch = await reader.read_registers_batch([(159, 4)])
            regs = batch[0]
            current_p = round(_signed16(regs[0]) * 0.1, 1)
            target_p = round(_signed16(regs[1]) * 0.1, 1)
            current_q = round(_signed16(regs[2]) * 0.1, 1)
            target_q = round(_signed16(regs[3]) * 0.1, 1)
            # Config raw = target value × 10 (the setpoint controller is configured to)
            config_p_raw = _signed16(regs[1])
            config_q_raw = _signed16(regs[3])
        except Exception as exc:
            logger.warning("Power limit direct read failed device=%d: %s, using Redis", device_id, exc)
            # Fallback to Redis cached data
            current_p = mx.get("current_p_pct")
            target_p = mx.get("target_p_pct")
            current_q = mx.get("current_q_pct")
            target_q = mx.get("target_q_pct")
            if target_p is not None:
                config_p_raw = round(target_p * 10)
            if target_q is not None:
                config_q_raw = round(target_q * 10)

        return PowerLimitResponse(
            success=True,
            message="Power limit read OK",
            device_id=device_id,
            device_type=device_type,
            current_p_pct=current_p,
            target_p_pct=target_p,
            current_q_pct=current_q,
            target_q_pct=target_q,
            config_p_raw=config_p_raw,
            config_q_raw=config_q_raw,
        )

    elif device_type == "ats":
        # HGM9560: read config registers 4351+4352+4354
        load_mode = None
        config_p_raw = None
        config_q_raw = None
        try:
            batch = await reader.read_registers_batch([
                (4351, 1),  # LoadMode
                (4352, 1),  # P%
                (4354, 1),  # Q%
            ])
            load_mode = batch[0][0]
            config_p_raw = batch[1][0]
            config_q_raw = batch[2][0]
        except Exception as exc:
            logger.warning("SPR power limit config read failed device=%d: %s", device_id, exc)

        return PowerLimitResponse(
            success=True,
            message="Power limit read OK (SPR)",
            device_id=device_id,
            device_type=device_type,
            config_p_raw=config_p_raw,
            config_q_raw=config_q_raw,
            current_p_pct=config_p_raw / 10 if config_p_raw is not None else None,
            target_p_pct=config_p_raw / 10 if config_p_raw is not None else None,
            current_q_pct=config_q_raw / 10 if config_q_raw is not None else None,
            target_q_pct=config_q_raw / 10 if config_q_raw is not None else None,
            load_mode=load_mode,
            load_mode_text=LOAD_MODE_TEXT.get(load_mode, f"unknown_{load_mode}") if load_mode is not None else None,
            power_limit_active=mx.get("power_limit_active"),
            power_limit_trip=mx.get("power_limit_trip"),
        )

    else:
        raise HTTPException(400, f"Unknown device type: {device_type}")


# --- POST endpoint ---

@router.post("/{device_id}/power-limit", response_model=PowerLimitWriteResponse)
async def set_power_limit(
    device_id: int, body: PowerLimitWriteRequest, request: Request,
):
    """Write power limit configuration to a device controller.

    - HGM9520N: writes P% to reg 4368, Q% to reg 4370
    - HGM9560:  writes LoadMode to 4351, P% to 4352, Q% to 4354
    All writes include verify-readback.
    """

    if body.p_raw < 0 or body.p_raw > 1000:
        raise HTTPException(400, "p_raw must be 0-1000 (0.0-100.0%)")
    if body.q_raw < 0 or body.q_raw > 1000:
        raise HTTPException(400, "q_raw must be 0-1000 (0.0-100.0%)")

    reader = _get_reader(request, device_id)
    device_type = _get_device_type(reader)

    if device_type == "generator":
        # HGM9520N: write P% → 4368, Q% → 4370
        writes = [
            (4368, body.p_raw),
            (4370, body.q_raw),
        ]
    elif device_type == "ats":
        # HGM9560: write LoadMode + P% + Q%
        if body.load_mode is not None and body.load_mode not in (0, 1, 2):
            raise HTTPException(400, "load_mode must be 0, 1, or 2")
        writes = []
        if body.load_mode is not None:
            writes.append((4351, body.load_mode))
        writes.append((4352, body.p_raw))
        writes.append((4354, body.q_raw))
    else:
        raise HTTPException(400, f"Unknown device type: {device_type}")

    try:
        verify_results = await reader.write_registers_batch(writes)

        # Check verification
        verified = True
        verify_dict = {}
        if verify_results:
            for i, (addr, expected) in enumerate(writes):
                actual = verify_results[i]
                verify_dict[f"0x{addr:04X}"] = {
                    "wrote": expected, "read_back": actual,
                    "ok": actual == expected,
                }
                if actual != expected:
                    verified = False

        msg = "Power limit written"
        if verified:
            msg += " and verified OK"
        else:
            msg += (
                " (echo OK, but verify-read shows old values"
                " — firmware may not support these registers)"
            )

        logger.info(
            "Power limit write: device=%d type=%s P=%d Q=%d mode=%s verified=%s",
            device_id, device_type, body.p_raw, body.q_raw, body.load_mode, verified,
        )

        return PowerLimitWriteResponse(
            success=True,
            message=msg,
            device_id=device_id,
            device_type=device_type,
            p_raw=body.p_raw,
            q_raw=body.q_raw,
            load_mode=body.load_mode,
            verified=verified,
            verify_values=verify_dict if verify_dict else None,
        )
    except ConnectionError as exc:
        raise HTTPException(502, f"Connection error: {exc}")
    except Exception as exc:
        logger.error("Power limit write failed: device=%d: %s", device_id, exc)
        raise HTTPException(500, f"Power limit write failed: {exc}")
