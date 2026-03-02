"""Commands API — send FC05 (Write Coil) / FC06 (Write Register) / FC03 (Read) to controllers."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from models.base import async_session
from models.scada_event import ScadaEvent

router = APIRouter(prefix="/api/commands", tags=["commands"])

logger = logging.getLogger("scada.commands")


# ---------------------------------------------------------------------------
# Helper: log operator command as SCADA event
# ---------------------------------------------------------------------------

COMMAND_LABELS = {
    "fc05": "Coil-команда",
    "fc06": "Запись регистра",
    "reset": "Сброс аварии",
    "spr_config": "Уставка мощности",
}


async def _log_operator_event(
    device_id: int,
    event_code: str,
    message: str,
    details: dict | None = None,
    redis=None,
) -> None:
    """Persist an OPERATOR event to scada_events and publish via Redis."""
    try:
        async with async_session() as session:
            ev = ScadaEvent(
                device_id=device_id,
                category="OPERATOR",
                event_code=event_code,
                message=message,
                details=details,
            )
            session.add(ev)
            await session.commit()
            await session.refresh(ev)
        # Publish for frontend WS bridge
        if redis:
            try:
                await redis.publish("events:new", json.dumps({
                    "id": ev.id,
                    "device_id": ev.device_id,
                    "category": "OPERATOR",
                    "event_code": event_code,
                    "message": message,
                    "created_at": ev.created_at.isoformat() if ev.created_at else None,
                }, default=str))
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Failed to log operator event: %s", exc)


class CommandRequest(BaseModel):
    device_id: int
    function_code: int  # 5 = FC05, 6 = FC06
    address: int
    value: int


class CommandResponse(BaseModel):
    success: bool
    message: str
    device_id: int
    function_code: int
    address: int
    value: int


@router.post("", response_model=CommandResponse)
async def send_command(cmd: CommandRequest, request: Request):
    """Send a Modbus write command to a device controller."""

    if cmd.function_code not in (5, 6):
        raise HTTPException(400, "function_code must be 5 (FC05 Write Coil) or 6 (FC06 Write Register)")

    poller = getattr(request.app.state, "poller", None)
    if poller is None:
        raise HTTPException(503, "Poller not initialized")

    readers = getattr(poller, "_readers", {})
    reader = readers.get(cmd.device_id)
    if reader is None:
        raise HTTPException(404, f"Device {cmd.device_id} not found in active readers")

    logger.info(
        "Command request: device=%d fc=%d addr=0x%04X value=%d reader=%s",
        cmd.device_id, cmd.function_code, cmd.address, cmd.value,
        type(reader).__name__,
    )

    try:
        if cmd.function_code == 5:
            # SmartGen pulse coil: OFF → ON → 600ms → OFF (guaranteed rising edge)
            await reader.write_coil(cmd.address, False)
            await asyncio.sleep(0.1)
            await reader.write_coil(cmd.address, True)
            logger.info(
                "FC05 Pulse Coil ON: device=%d addr=0x%04X",
                cmd.device_id, cmd.address,
            )
            await asyncio.sleep(0.6)
            await reader.write_coil(cmd.address, False)
            logger.info(
                "FC05 Pulse Coil OFF: device=%d addr=0x%04X (complete)",
                cmd.device_id, cmd.address,
            )
        else:
            await reader.write_register(cmd.address, cmd.value)
            logger.info(
                "FC06 Write Register: device=%d addr=0x%04X value=%d",
                cmd.device_id, cmd.address, cmd.value,
            )

        msg = f"FC{cmd.function_code:02d} sent OK"
        # Log operator event
        redis = getattr(request.app.state, "redis", None)
        await _log_operator_event(
            device_id=cmd.device_id,
            event_code=f"cmd_fc{cmd.function_code:02d}",
            message=f"🎛 Оператор: FC{cmd.function_code:02d} addr=0x{cmd.address:04X} val={cmd.value}",
            details={"fc": cmd.function_code, "address": cmd.address, "value": cmd.value},
            redis=redis,
        )
        return CommandResponse(
            success=True,
            message=msg,
            device_id=cmd.device_id,
            function_code=cmd.function_code,
            address=cmd.address,
            value=cmd.value,
        )
    except ConnectionError as exc:
        logger.error(
            "Command ConnectionError: device=%d fc=%d addr=0x%04X: %s",
            cmd.device_id, cmd.function_code, cmd.address, exc,
        )
        raise HTTPException(502, f"Connection error: {exc}")
    except Exception as exc:
        logger.error(
            "Command failed: device=%d fc=%d addr=0x%04X: %s",
            cmd.device_id, cmd.function_code, cmd.address, exc,
            exc_info=True,
        )
        raise HTTPException(500, f"Command failed: {exc}")


# --- Smart Reset with verification ---

class ResetResponse(BaseModel):
    success: bool
    message: str
    device_id: int
    alarm_before: dict
    alarm_after: dict
    cleared: bool


@router.post("/reset/{device_id}")
async def reset_alarm(device_id: int, request: Request):
    """Smart alarm reset — tries multiple strategies:
    1. Ensure Stop mode → send Stop coil again (physical-panel behavior)
    2. Mute (coil 12) → Reset (coil 17) simple ON
    3. Reset (coil 17) pulse OFF→ON→2s→OFF
    Returns which strategy worked (if any).
    """

    poller = getattr(request.app.state, "poller", None)
    if poller is None:
        raise HTTPException(503, "Poller not initialized")

    readers = getattr(poller, "_readers", {})
    reader = readers.get(device_id)
    if reader is None:
        raise HTTPException(404, f"Device {device_id} not found")

    async def read_alarm_state():
        """Read status (reg 0) + alarm detail (reg 1-6) from HGM9520N."""
        try:
            regs = await reader.read_registers(0, 7)
            status = regs[0] if regs else 0
            return {
                "status_raw": status,
                "alarm_common": bool(status & 1),
                "alarm_shutdown": bool(status & 2),
                "alarm_warning": bool(status & 4),
                "mode_auto": bool(status & (1 << 9)),
                "mode_manual": bool(status & (1 << 10)),
                "mode_stop": bool(status & (1 << 11)),
                "alarm_sd_0": regs[1] if len(regs) > 1 else 0,
                "alarm_sd_1": regs[2] if len(regs) > 2 else 0,
                "alarm_sd_2": regs[3] if len(regs) > 3 else 0,
                "alarm_sd_3": regs[4] if len(regs) > 4 else 0,
                "alarm_sd_4": regs[5] if len(regs) > 5 else 0,
                "alarm_sd_5": regs[6] if len(regs) > 6 else 0,
            }
        except Exception as e:
            return {"error": str(e)}

    def is_alarm_active(state: dict) -> bool:
        return state.get("alarm_common", False) or state.get("alarm_shutdown", False)

    strategies_tried = []

    try:
        alarm_before = await read_alarm_state()
        logger.info("Reset device=%d: alarm_before=%s", device_id, alarm_before)

        if not is_alarm_active(alarm_before):
            return ResetResponse(
                success=True,
                message="Аварий нет — сброс не требуется",
                device_id=device_id,
                alarm_before=alarm_before,
                alarm_after=alarm_before,
                cleared=True,
            )

        # ── Strategy 1: Stop-while-in-Stop ──
        # SmartGen docs: "In Stop mode, pressing Stop resets alarms"
        # Ensure Stop mode first, then pulse Stop again
        logger.info("Reset device=%d: Strategy 1 — Stop-in-Stop", device_id)
        strategies_tried.append("Stop-in-Stop")

        # Pulse Stop to ensure Stop mode
        await reader.write_coil(0x0001, True)
        await asyncio.sleep(0.5)
        await reader.write_coil(0x0001, False)
        await asyncio.sleep(1.0)

        # Now send Stop AGAIN — acts as reset on physical panel
        await reader.write_coil(0x0001, True)
        await asyncio.sleep(0.5)
        await reader.write_coil(0x0001, False)
        await asyncio.sleep(2.0)

        state1 = await read_alarm_state()
        logger.info("Reset device=%d: after Stop-in-Stop: %s", device_id, state1)

        if not is_alarm_active(state1):
            return ResetResponse(
                success=True,
                message="✅ Авария сброшена (метод: повторный Stop)",
                device_id=device_id,
                alarm_before=alarm_before,
                alarm_after=state1,
                cleared=True,
            )

        # ── Strategy 2: Mute + Reset (simple ON, no pulse) ──
        # Some SmartGen models need Mute first, and coil as simple write (not pulse)
        logger.info("Reset device=%d: Strategy 2 — Mute + Reset (simple ON)", device_id)
        strategies_tried.append("Mute+Reset-ON")

        # Mute alarm horn (coil 12)
        await reader.write_coil(0x000C, True)
        await asyncio.sleep(0.3)

        # Reset (coil 17) — simple ON (like GUI monitor does)
        await reader.write_coil(0x0011, True)
        await asyncio.sleep(3.0)
        await reader.write_coil(0x0011, False)
        await asyncio.sleep(0.3)
        await reader.write_coil(0x000C, False)
        await asyncio.sleep(2.0)

        state2 = await read_alarm_state()
        logger.info("Reset device=%d: after Mute+Reset: %s", device_id, state2)

        if not is_alarm_active(state2):
            return ResetResponse(
                success=True,
                message="✅ Авария сброшена (метод: Mute + Reset)",
                device_id=device_id,
                alarm_before=alarm_before,
                alarm_after=state2,
                cleared=True,
            )

        # ── Strategy 3: Manual → Reset pulse ──
        logger.info("Reset device=%d: Strategy 3 — Manual + Reset pulse", device_id)
        strategies_tried.append("Manual+Reset-pulse")

        # Switch to Manual
        await reader.write_coil(0x0004, True)
        await asyncio.sleep(0.3)
        await reader.write_coil(0x0004, False)
        await asyncio.sleep(1.0)

        # Reset pulse OFF→ON→2s→OFF
        await reader.write_coil(0x0011, False)
        await asyncio.sleep(0.1)
        await reader.write_coil(0x0011, True)
        await asyncio.sleep(2.0)
        await reader.write_coil(0x0011, False)
        await asyncio.sleep(2.0)

        state3 = await read_alarm_state()
        logger.info("Reset device=%d: after Manual+Reset: %s", device_id, state3)

        # Return Stop mode after attempts
        await reader.write_coil(0x0001, True)
        await asyncio.sleep(0.3)
        await reader.write_coil(0x0001, False)

        cleared = not is_alarm_active(state3)
        alarm_after = state3

        strats_text = ", ".join(strategies_tried)
        msg = f"✅ Авария сброшена (метод: Manual + Reset)" if cleared else (
            f"⚠ Авария НЕ сбросилась.\n"
            f"Пробовали: {strats_text}\n"
            f"Возможные причины:\n"
            f"• Параметр Remote Alarm Reset Enable выключен в настройках контроллера\n"
            f"• Условие аварии всё ещё активно (проверьте датчики)\n"
            f"• Попробуйте через ПО SmartGen PC Suite: Settings → Remote Control → Enable Remote Reset"
        )

        # Log operator event
        redis = getattr(request.app.state, "redis", None)
        ev_msg = f"🔄 Оператор: сброс аварии → {'✅ успешно' if cleared else '⚠ не удалось'}"
        await _log_operator_event(
            device_id=device_id,
            event_code="cmd_reset",
            message=ev_msg,
            details={"cleared": cleared, "strategies": strategies_tried},
            redis=redis,
        )

        return ResetResponse(
            success=cleared,
            message=msg,
            device_id=device_id,
            alarm_before=alarm_before,
            alarm_after=alarm_after,
            cleared=cleared,
        )

    except ConnectionError as exc:
        raise HTTPException(502, f"Connection error: {exc}")
    except Exception as exc:
        logger.error("Reset failed: device=%d: %s", device_id, exc, exc_info=True)
        raise HTTPException(500, f"Reset failed: {exc}")


# --- Read registers (FC03) ---

class ReadRegistersRequest(BaseModel):
    device_id: int
    address: int
    count: int = 1


class ReadRegistersResponse(BaseModel):
    success: bool
    message: str
    device_id: int
    address: int
    count: int
    registers: list[int]


@router.post("/read-registers", response_model=ReadRegistersResponse)
async def read_registers(req: ReadRegistersRequest, request: Request):
    """Read holding registers (FC03) from a device controller."""

    if req.count < 1 or req.count > 125:
        raise HTTPException(400, "count must be 1-125")

    poller = getattr(request.app.state, "poller", None)
    if poller is None:
        raise HTTPException(503, "Poller not initialized")

    readers = getattr(poller, "_readers", {})
    reader = readers.get(req.device_id)
    if reader is None:
        raise HTTPException(404, f"Device {req.device_id} not found in active readers")

    try:
        regs = await reader.read_registers(req.address, req.count)
        logger.info(
            "FC03 Read: device=%d addr=0x%04X count=%d values=%s",
            req.device_id, req.address, req.count, regs,
        )
        return ReadRegistersResponse(
            success=True,
            message=f"FC03 read OK: {req.count} registers from 0x{req.address:04X}",
            device_id=req.device_id,
            address=req.address,
            count=req.count,
            registers=regs,
        )
    except ConnectionError as exc:
        raise HTTPException(502, f"Connection error: {exc}")
    except Exception as exc:
        logger.error(
            "Read failed: device=%d addr=0x%04X count=%d: %s",
            req.device_id, req.address, req.count, exc,
        )
        raise HTTPException(500, f"Read failed: {exc}")


# --- Scan config registers (diagnostic tool) ---

@router.post("/scan-config/{device_id}")
async def scan_config_registers(device_id: int, request: Request):
    """Scan configuration register ranges to find Remote Alarm Reset Enable
    and other control settings. HGM9520N config is in 4096-4500 range."""

    poller = getattr(request.app.state, "poller", None)
    if poller is None:
        raise HTTPException(503, "Poller not initialized")

    readers = getattr(poller, "_readers", {})
    reader = readers.get(device_id)
    if reader is None:
        raise HTTPException(404, f"Device {device_id} not found")

    # Known config register ranges for HGM9520N
    scan_ranges = [
        (4096, 40, "General Config 4096-4135"),
        (4136, 40, "Config 4136-4175"),
        (4176, 40, "Config 4176-4215"),
        (4216, 40, "Config 4216-4255"),
        (4256, 40, "Config 4256-4295"),
        (4296, 40, "Config 4296-4335"),
        (4336, 40, "Config 4336-4375 (includes P%/Q%)"),
        (4376, 40, "Config 4376-4415"),
        (4800, 40, "Extended Config 4800-4839"),
        (4840, 40, "Extended Config 4840-4879"),
    ]

    results = {}
    errors = []

    for start_addr, count, label in scan_ranges:
        try:
            regs = await reader.read_registers(start_addr, count)
            non_zero = {}
            for i, v in enumerate(regs):
                addr = start_addr + i
                non_zero[str(addr)] = v
            results[label] = non_zero
            logger.info(
                "Config scan device=%d: %s (%d-%d): %s",
                device_id, label, start_addr, start_addr + count - 1,
                {k: v for k, v in non_zero.items() if v != 0},
            )
        except Exception as e:
            errors.append(f"{label}: {e}")
            logger.warning("Config scan failed: device=%d %s: %s", device_id, label, e)

    # Highlight interesting registers (non-zero, possible enable/disable flags)
    flags = {}
    for label, regs_dict in results.items():
        for addr_str, val in regs_dict.items():
            if val in (0, 1):
                flags[addr_str] = {"value": val, "note": "Boolean flag (0/1)", "section": label}
            elif val != 0 and val < 10:
                flags[addr_str] = {"value": val, "note": f"Small value ({val})", "section": label}

    return {
        "success": True,
        "device_id": device_id,
        "scan_ranges": len(scan_ranges),
        "errors": errors,
        "boolean_flags": flags,
        "all_registers": results,
    }


# --- Read SPR config (high-level: LoadMode + P% + Q%) ---

class SprConfigResponse(BaseModel):
    success: bool
    message: str
    device_id: int
    load_mode: int | None = None
    load_mode_text: str | None = None
    p_percent: float | None = None
    p_raw: int | None = None
    q_percent: float | None = None
    q_raw: int | None = None


LOAD_MODE_TEXT = {0: "Gen Control", 1: "Mains Control", 2: "Load Reception"}


@router.get("/spr-config/{device_id}", response_model=SprConfigResponse)
async def read_spr_config(device_id: int, request: Request):
    """Read SPR (HGM9560) configuration: LoadMode, P%, Q% from controller registers."""

    poller = getattr(request.app.state, "poller", None)
    if poller is None:
        raise HTTPException(503, "Poller not initialized")

    readers = getattr(poller, "_readers", {})
    reader = readers.get(device_id)
    if reader is None:
        raise HTTPException(404, f"Device {device_id} not found in active readers")

    try:
        # Atomic batch read: all 3 config registers under one lock
        batch = await reader.read_registers_batch([
            (4351, 1),  # LoadMode
            (4352, 1),  # P%
            (4354, 1),  # Q%
        ])
        load_mode = batch[0][0]
        p_raw = batch[1][0]
        q_raw = batch[2][0]

        logger.info(
            "SPR config read: device=%d LoadMode=%d P=%d(%.1f%%) Q=%d(%.1f%%)",
            device_id, load_mode, p_raw, p_raw / 10, q_raw, q_raw / 10,
        )

        return SprConfigResponse(
            success=True,
            message="SPR config read OK",
            device_id=device_id,
            load_mode=load_mode,
            load_mode_text=LOAD_MODE_TEXT.get(load_mode, f"unknown_{load_mode}"),
            p_percent=round(p_raw / 10, 1),
            p_raw=p_raw,
            q_percent=round(q_raw / 10, 1),
            q_raw=q_raw,
        )
    except ConnectionError as exc:
        raise HTTPException(502, f"Connection error: {exc}")
    except Exception as exc:
        logger.error("SPR config read failed: device=%d: %s", device_id, exc)
        raise HTTPException(500, f"SPR config read failed: {exc}")


# --- Write SPR config (high-level: LoadMode + P% + Q%) ---
# HGM9560 Communication Protocol V1.1 (2023-05-05) added FC06 for registers:
#   4351 — Load Mode (0=Gen Control, 1=Mains Control, 2=Load Reception)
#   4352 — Load Parallel Output Active Power Percentage (0-1000 → 0.0-100.0%)
#   4354 — Load Parallel Output Reactive Power Percentage (0-1000 → 0.0-100.0%)
# NOTE: Controllers with firmware older than V1.1 may echo FC06 OK but
#       silently ignore writes to 4351-4354. Verify-read detects this.


class SprConfigWriteRequest(BaseModel):
    load_mode: int  # 0=Gen Control, 1=Mains Control, 2=Load Reception
    p_raw: int      # P% × 10 (0-1000 → 0.0-100.0%)
    q_raw: int      # Q% × 10 (0-1000 → 0.0-100.0%)


class SprConfigWriteResponse(BaseModel):
    success: bool
    message: str
    device_id: int
    load_mode: int
    p_raw: int
    q_raw: int
    verified: bool
    verify_values: dict | None = None


@router.post("/spr-config/{device_id}", response_model=SprConfigWriteResponse)
async def write_spr_config(
    device_id: int, body: SprConfigWriteRequest, request: Request,
):
    """Write SPR (HGM9560) configuration: LoadMode, P%, Q% to controller registers.

    Writes 3 config registers atomically (under one lock) and reads them back
    to verify.  Requires firmware >= V1.1 (2023-05-05).
    """
    if body.load_mode not in (0, 1, 2):
        raise HTTPException(400, "load_mode must be 0, 1, or 2")
    if body.p_raw < 0 or body.p_raw > 1000:
        raise HTTPException(400, "p_raw must be 0-1000")
    if body.q_raw < 0 or body.q_raw > 1000:
        raise HTTPException(400, "q_raw must be 0-1000")

    poller = getattr(request.app.state, "poller", None)
    if poller is None:
        raise HTTPException(503, "Poller not initialized")

    readers = getattr(poller, "_readers", {})
    reader = readers.get(device_id)
    if reader is None:
        raise HTTPException(404, f"Device {device_id} not found in active readers")

    try:
        writes = [
            (4351, body.load_mode),  # LoadMode
            (4352, body.p_raw),      # P%
            (4354, body.q_raw),      # Q%
        ]

        verify_results = await reader.write_registers_batch(writes)

        # Check verification results
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

        msg = "SPR config written"
        if verified:
            msg += " and verified OK"
        else:
            msg += (
                " (echo OK, but verify-read shows old values"
                " — firmware may be older than V1.1 or controller is in read-only state)"
            )

        logger.info(
            "SPR config write: device=%d mode=%d P=%d Q=%d verified=%s",
            device_id, body.load_mode, body.p_raw, body.q_raw, verified,
        )

        # Log operator event
        redis = getattr(request.app.state, "redis", None)
        mode_name = {0: "Gen Control", 1: "Mains Control", 2: "Load Reception"}.get(body.load_mode, "?")
        await _log_operator_event(
            device_id=device_id,
            event_code="cmd_spr_config",
            message=f"⚡ Оператор: уставка P={body.p_raw/10:.1f}% Q={body.q_raw/10:.1f}% mode={mode_name}",
            details={"load_mode": body.load_mode, "p_raw": body.p_raw, "q_raw": body.q_raw, "verified": verified},
            redis=redis,
        )

        return SprConfigWriteResponse(
            success=True,
            message=msg,
            device_id=device_id,
            load_mode=body.load_mode,
            p_raw=body.p_raw,
            q_raw=body.q_raw,
            verified=verified,
            verify_values=verify_dict if verify_dict else None,
        )
    except ConnectionError as exc:
        raise HTTPException(502, f"Connection error: {exc}")
    except Exception as exc:
        logger.error("SPR config write failed: device=%d: %s", device_id, exc)
        raise HTTPException(500, f"SPR config write failed: {exc}")
