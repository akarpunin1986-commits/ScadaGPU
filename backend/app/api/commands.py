"""Commands API — send FC05 (Write Coil) / FC06 (Write Register) / FC03 (Read) to controllers."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/commands", tags=["commands"])

logger = logging.getLogger("scada.commands")


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
            await reader.write_coil(cmd.address, bool(cmd.value))
            logger.info(
                "FC05 Write Coil: device=%d addr=0x%04X value=%s",
                cmd.device_id, cmd.address, bool(cmd.value),
            )
        else:
            await reader.write_register(cmd.address, cmd.value)
            logger.info(
                "FC06 Write Register: device=%d addr=0x%04X value=%d",
                cmd.device_id, cmd.address, cmd.value,
            )

        msg = f"FC{cmd.function_code:02d} sent OK"
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
