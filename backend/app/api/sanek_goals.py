"""API for Sanek goals and actions (autopilot control layer)."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from models import async_session
from models.sanek_goal import SanekGoal
from models.sanek_action import SanekAction
from models.device import Device

logger = logging.getLogger("scada.sanek_goals")

router = APIRouter(prefix="/api/sanek", tags=["sanek-goals"])

# ── Action expiry: 5 minutes ──
ACTION_EXPIRY_SECONDS = 300


# ── Pydantic schemas ──

class GoalCreate(BaseModel):
    site_id: int
    description: str
    goal_type: str  # power_target, efficiency_target, schedule, custom
    target_config: dict = {}
    safety_limits: dict = {}
    priority: int = 3


class GoalUpdate(BaseModel):
    status: str | None = None
    description: str | None = None
    target_config: dict | None = None
    safety_limits: dict | None = None
    priority: int | None = None


class ActionPropose(BaseModel):
    device_id: int
    action_type: str  # set_power_limit, start_generator, stop_generator
    params: dict = {}
    reason: str
    goal_id: int | None = None
    chat_session_id: str | None = None


class ActionExecuteResult(BaseModel):
    action_id: int
    status: str
    result: dict | None = None
    error: str | None = None


# ── Goals CRUD ──

@router.get("/goals")
async def list_goals(site_id: int | None = None, status: str | None = None):
    """List goals, optionally filtered by site and status."""
    async with async_session() as session:
        q = select(SanekGoal)
        if site_id:
            q = q.where(SanekGoal.site_id == site_id)
        if status:
            q = q.where(SanekGoal.status == status)
        q = q.order_by(SanekGoal.priority, SanekGoal.created_at.desc())
        rows = (await session.execute(q)).scalars().all()
        return [_goal_to_dict(g) for g in rows]


@router.post("/goals")
async def create_goal(body: GoalCreate):
    """Create a new goal."""
    async with async_session() as session:
        goal = SanekGoal(
            site_id=body.site_id,
            description=body.description,
            goal_type=body.goal_type,
            target_config=body.target_config,
            safety_limits=body.safety_limits,
            priority=body.priority,
        )
        session.add(goal)
        await session.commit()
        await session.refresh(goal)
        logger.info("Goal created: #%d '%s'", goal.id, goal.description)
        return _goal_to_dict(goal)


@router.put("/goals/{goal_id}")
async def update_goal(goal_id: int, body: GoalUpdate):
    """Update a goal (status, config, etc.)."""
    async with async_session() as session:
        goal = await session.get(SanekGoal, goal_id)
        if not goal:
            raise HTTPException(404, "Goal not found")
        if body.status is not None:
            goal.status = body.status
        if body.description is not None:
            goal.description = body.description
        if body.target_config is not None:
            goal.target_config = body.target_config
        if body.safety_limits is not None:
            goal.safety_limits = body.safety_limits
        if body.priority is not None:
            goal.priority = body.priority
        goal.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(goal)
        return _goal_to_dict(goal)


@router.delete("/goals/{goal_id}")
async def cancel_goal(goal_id: int):
    """Cancel (soft-delete) a goal."""
    async with async_session() as session:
        goal = await session.get(SanekGoal, goal_id)
        if not goal:
            raise HTTPException(404, "Goal not found")
        goal.status = "cancelled"
        goal.updated_at = datetime.utcnow()
        await session.commit()
        return {"ok": True, "goal_id": goal_id, "status": "cancelled"}


# ── Actions ──

@router.post("/actions/propose")
async def propose_action(body: ActionPropose):
    """Propose a control action (requires operator confirmation to execute)."""
    # Validate device exists
    async with async_session() as session:
        device = await session.get(Device, body.device_id)
        if not device:
            raise HTTPException(404, f"Device {body.device_id} not found")

        # Validate action type
        valid_types = {"set_power_limit", "start_generator", "stop_generator"}
        if body.action_type not in valid_types:
            raise HTTPException(400, f"Invalid action_type. Must be one of: {valid_types}")

        # Validate params for set_power_limit
        if body.action_type == "set_power_limit":
            p_raw = body.params.get("p_raw")
            q_raw = body.params.get("q_raw", 0)
            if p_raw is None:
                raise HTTPException(400, "set_power_limit requires params.p_raw")
            if not (0 <= int(p_raw) <= 1000):
                raise HTTPException(400, "p_raw must be 0-1000 (0.0-100.0%)")
            if not (0 <= int(q_raw) <= 1000):
                raise HTTPException(400, "q_raw must be 0-1000 (0.0-100.0%)")

        # Expire any pending actions for same device (avoid stacking)
        await session.execute(
            update(SanekAction)
            .where(SanekAction.device_id == body.device_id)
            .where(SanekAction.status == "proposed")
            .values(status="expired")
        )

        action = SanekAction(
            device_id=body.device_id,
            site_id=device.site_id,
            action_type=body.action_type,
            params=body.params,
            reason=body.reason,
            goal_id=body.goal_id,
            chat_session_id=body.chat_session_id,
        )
        session.add(action)
        await session.commit()
        await session.refresh(action)

        logger.info(
            "Action proposed: #%d %s on device %d (%s)",
            action.id, action.action_type, body.device_id, device.name,
        )
        return _action_to_dict(action, device_name=device.name)


@router.post("/actions/{action_id}/execute")
async def execute_action(action_id: int, request: Request):
    """Execute a previously proposed action after operator confirmation."""
    async with async_session() as session:
        action = await session.get(SanekAction, action_id)
        if not action:
            raise HTTPException(404, f"Action #{action_id} not found")

        # Check status
        if action.status != "proposed":
            raise HTTPException(400, f"Action #{action_id} is '{action.status}', expected 'proposed'")

        # Check expiry (5 min)
        if datetime.utcnow() - action.proposed_at > timedelta(seconds=ACTION_EXPIRY_SECONDS):
            action.status = "expired"
            await session.commit()
            raise HTTPException(400, f"Action #{action_id} expired (>5 min since proposal)")

        # Mark as confirmed + executing
        action.status = "executing"
        action.confirmed_at = datetime.utcnow()
        await session.commit()

        # Get device info
        device = await session.get(Device, action.device_id)
        if not device:
            action.status = "failed"
            action.error = "Device not found"
            await session.commit()
            raise HTTPException(404, "Device not found")

        # Execute the actual command
        try:
            result = await _execute_command(action, device, request)
            action.status = "completed"
            action.executed_at = datetime.utcnow()
            action.result = result
            await session.commit()
            logger.info("Action #%d executed successfully: %s", action_id, result)
            return {
                "ok": True,
                "action_id": action_id,
                "status": "completed",
                "result": result,
            }
        except Exception as e:
            action.status = "failed"
            action.error = str(e)
            action.executed_at = datetime.utcnow()
            await session.commit()
            logger.error("Action #%d failed: %s", action_id, e)
            raise HTTPException(500, f"Action execution failed: {e}")


@router.get("/actions")
async def list_actions(
    device_id: int | None = None,
    status: str | None = None,
    limit: int = 20,
):
    """List recent actions."""
    async with async_session() as session:
        q = select(SanekAction)
        if device_id:
            q = q.where(SanekAction.device_id == device_id)
        if status:
            q = q.where(SanekAction.status == status)
        q = q.order_by(SanekAction.proposed_at.desc()).limit(limit)
        rows = (await session.execute(q)).scalars().all()
        return [_action_to_dict(a) for a in rows]


@router.get("/actions/{action_id}")
async def get_action(action_id: int):
    """Get action details."""
    async with async_session() as session:
        action = await session.get(SanekAction, action_id)
        if not action:
            raise HTTPException(404, "Action not found")
        return _action_to_dict(action)


# ── Execution engine ──

async def _execute_command(action: SanekAction, device: Device, request: Request) -> dict:
    """Execute a control command on the device via internal API."""
    import httpx

    base_url = "http://127.0.0.1:8010"

    if action.action_type == "set_power_limit":
        p_raw = int(action.params.get("p_raw", 0))
        q_raw = int(action.params.get("q_raw", 0))
        payload = {"p_raw": p_raw, "q_raw": q_raw}

        # For HGM9560 (ATS/SPR), include load_mode if specified
        if action.params.get("load_mode") is not None:
            payload["load_mode"] = int(action.params["load_mode"])

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base_url}/api/devices/{action.device_id}/power-limit",
                json=payload,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Power limit API error {resp.status_code}: {resp.text}")
            return resp.json()

    elif action.action_type == "start_generator":
        # SmartGen start: FC05 coil pulse
        # Standard start coil address for HGM9520N = 100 (coil 0x0064)
        coil_addr = int(action.params.get("coil_address", 100))
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base_url}/api/commands",
                json={
                    "device_id": action.device_id,
                    "function_code": 5,
                    "address": coil_addr,
                    "value": 1,
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Command API error {resp.status_code}: {resp.text}")
            return resp.json()

    elif action.action_type == "stop_generator":
        # SmartGen stop: FC05 coil pulse
        # Standard stop coil address for HGM9520N = 101 (coil 0x0065)
        coil_addr = int(action.params.get("coil_address", 101))
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{base_url}/api/commands",
                json={
                    "device_id": action.device_id,
                    "function_code": 5,
                    "address": coil_addr,
                    "value": 1,
                },
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Command API error {resp.status_code}: {resp.text}")
            return resp.json()

    else:
        raise RuntimeError(f"Unknown action_type: {action.action_type}")


# ── Serializers ──

def _goal_to_dict(g: SanekGoal) -> dict:
    return {
        "id": g.id,
        "site_id": g.site_id,
        "description": g.description,
        "goal_type": g.goal_type,
        "target_config": g.target_config,
        "safety_limits": g.safety_limits,
        "status": g.status,
        "priority": g.priority,
        "created_at": g.created_at.isoformat() if g.created_at else None,
        "updated_at": g.updated_at.isoformat() if g.updated_at else None,
        "created_by": g.created_by,
        "last_check_at": g.last_check_at.isoformat() if g.last_check_at else None,
        "last_action_at": g.last_action_at.isoformat() if g.last_action_at else None,
        "actions_count": g.actions_count,
    }


def _action_to_dict(a: SanekAction, device_name: str | None = None) -> dict:
    return {
        "id": a.id,
        "device_id": a.device_id,
        "site_id": a.site_id,
        "device_name": device_name,
        "action_type": a.action_type,
        "params": a.params,
        "reason": a.reason,
        "status": a.status,
        "proposed_at": a.proposed_at.isoformat() if a.proposed_at else None,
        "confirmed_at": a.confirmed_at.isoformat() if a.confirmed_at else None,
        "executed_at": a.executed_at.isoformat() if a.executed_at else None,
        "result": a.result,
        "error": a.error,
        "goal_id": a.goal_id,
    }
