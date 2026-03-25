"""RuleEngine — evaluates ScadaRules against events and executes actions.

Background service: subscribes to alarms:new, periodically checks schedule/hours rules.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import settings
from models.base import async_session
from models.scada_rule import ScadaRule

logger = logging.getLogger("scada.rule_engine")

# Cooldown: don't re-trigger same rule within this period
COOLDOWN_SECONDS = 3600  # 1 hour

# How often to check schedule and hours rules (seconds)
RULE_CHECK_INTERVAL = getattr(settings, "RULE_CHECK_INTERVAL", 600)  # 10 min


class RuleEngine:
    """Processes active ScadaRules against incoming events.

    Also runs as a background service:
    - Subscribes to alarms:new → on_alarm()
    - Periodically checks schedule and hours rules
    """

    def __init__(self, redis, task_engine):
        self.redis = redis
        self.task_engine = task_engine
        self._running = False

    # ── Background service lifecycle ──────────────────────────
    async def start(self) -> None:
        """Start as background service."""
        self._running = True
        logger.info("RuleEngine started (alarm subscription + periodic checks every %ds)", RULE_CHECK_INTERVAL)
        asyncio.create_task(self._subscribe_alarms())
        while self._running:
            try:
                triggered = await self.check_schedule_rules()
                if triggered:
                    logger.info("Schedule rules triggered: %s", triggered)
                triggered = await self.check_hours_rules()
                if triggered:
                    logger.info("Hours rules triggered: %s", triggered)
            except Exception:
                logger.exception("RuleEngine periodic check error")
            try:
                await asyncio.sleep(RULE_CHECK_INTERVAL)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        self._running = False
        logger.info("RuleEngine stop requested")

    async def _subscribe_alarms(self) -> None:
        """Listen for new alarms and evaluate alarm-type rules."""
        try:
            pubsub = self.redis.pubsub()
            await pubsub.subscribe("alarms:new")
            logger.info("RuleEngine subscribed to alarms:new")
            async for msg in pubsub.listen():
                if not self._running:
                    break
                if msg["type"] != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                    triggered = await self.on_alarm(data)
                    if triggered:
                        logger.info("Alarm rules triggered: %s for alarm %s",
                                    triggered, data.get("alarm_name", "?"))
                except Exception:
                    logger.exception("RuleEngine alarm processing error")
        except Exception:
            logger.exception("RuleEngine alarm subscription error")

    # ── Alarm trigger ─────────────────────────────────────────────
    async def on_alarm(self, alarm_data: dict) -> list[int]:
        """Evaluate alarm-type rules against incoming alarm.

        Returns list of triggered rule IDs.
        """
        triggered: list[int] = []
        async with async_session() as session:
            stmt = (
                select(ScadaRule)
                .where(ScadaRule.trigger_type == "alarm", ScadaRule.is_active.is_(True))
            )
            rules = (await session.execute(stmt)).scalars().all()

            for rule in rules:
                if self._match_alarm(rule, alarm_data):
                    await self.execute_action(rule, context={"alarm": alarm_data}, session=session)
                    triggered.append(rule.id)

            if triggered:
                await session.commit()

        return triggered

    def _match_alarm(self, rule: ScadaRule, alarm_data: dict) -> bool:
        """Check if alarm matches rule's trigger_config."""
        cfg = rule.trigger_config or {}

        # Check equipment_code match (if rule is scoped)
        if rule.equipment_code and alarm_data.get("equipment_code") != rule.equipment_code:
            return False

        # Check site_id match
        if rule.site_id and alarm_data.get("site_id") != rule.site_id:
            return False

        # "any" — match all alarms
        if cfg.get("any"):
            return True

        # severity_min filter
        severity_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        if "severity_min" in cfg:
            alarm_sev = severity_order.get(alarm_data.get("severity", "LOW"), 0)
            min_sev = severity_order.get(cfg["severity_min"], 0)
            if alarm_sev < min_sev:
                return False

        # alarm_codes filter
        if "alarm_codes" in cfg:
            alarm_code = alarm_data.get("alarm_code")
            if alarm_code not in cfg["alarm_codes"]:
                return False

        return True

    # ── Metric threshold trigger ──────────────────────────────────
    async def on_metric_update(self, device_id: int, metric_name: str, value: float) -> list[int]:
        """Evaluate metric_threshold rules against a metric update.

        Returns list of triggered rule IDs.
        """
        triggered: list[int] = []
        async with async_session() as session:
            stmt = (
                select(ScadaRule)
                .where(ScadaRule.trigger_type == "metric_threshold", ScadaRule.is_active.is_(True))
            )
            rules = (await session.execute(stmt)).scalars().all()

            now = datetime.utcnow()
            for rule in rules:
                if self._match_metric(rule, device_id, metric_name, value):
                    # Cooldown check
                    if rule.last_triggered_at:
                        elapsed = (now - rule.last_triggered_at).total_seconds()
                        if elapsed < COOLDOWN_SECONDS:
                            continue

                    context = {
                        "device_id": device_id,
                        "metric_name": metric_name,
                        "value": value,
                    }
                    await self.execute_action(rule, context=context, session=session)
                    triggered.append(rule.id)

            if triggered:
                await session.commit()

        return triggered

    def _match_metric(self, rule: ScadaRule, device_id: int, metric_name: str, value: float) -> bool:
        """Check if metric update matches rule's trigger_config."""
        cfg = rule.trigger_config or {}
        if not cfg:
            return False

        # Device filter
        if "device_id" in cfg and cfg["device_id"] != device_id:
            return False

        # Metric name
        if cfg.get("metric") != metric_name:
            return False

        # Operator comparison
        threshold = cfg.get("value")
        operator = cfg.get("operator", ">")
        if threshold is None:
            return False

        if operator == ">" and value > threshold:
            return True
        if operator == ">=" and value >= threshold:
            return True
        if operator == "<" and value < threshold:
            return True
        if operator == "<=" and value <= threshold:
            return True
        if operator == "=" and value == threshold:
            return True
        if operator == "!=" and value != threshold:
            return True

        return False

    # ── Execute action ────────────────────────────────────────────
    async def execute_action(self, rule: ScadaRule, context: dict, session=None) -> None:
        """Execute the rule's action: create_task, notify, or both."""
        action = rule.action_type
        cfg = rule.action_config or {}

        action_ok = False
        try:
            if action in ("create_task", "create_task_and_notify"):
                await self._action_create_task(rule, cfg, context)

            if action in ("notify", "create_task_and_notify"):
                await self._action_notify(rule, cfg, context)

            # Notify watchers
            if rule.watchers:
                await self._notify_watchers(rule, context)

            action_ok = True
        except Exception as e:
            logger.exception("Rule %d (%s) action failed: %s", rule.id, rule.name, e)

        # Update stats only on success (so failed rules retry next cycle)
        now = datetime.utcnow()
        if action_ok:
            rule.times_triggered = (rule.times_triggered or 0) + 1
            rule.last_triggered_at = now

        # Log decision
        await self._log_decision(rule, context)

        logger.info(
            "Rule #%d '%s' triggered (type=%s, action=%s, total=%d)",
            rule.id, rule.name, rule.trigger_type, rule.action_type, rule.times_triggered,
        )

    async def _action_create_task(self, rule: ScadaRule, cfg: dict, context: dict) -> None:
        """Create a ScadaTask via TaskEngine."""
        alarm = context.get("alarm", {})
        metric = context.get("metric_name", "")
        title = cfg.get("title") or f"[Rule] {rule.name}"
        if alarm:
            title = f"[Alarm] {alarm.get('alarm_name', rule.name)}"

        await self.task_engine.create_task(
            task_type=cfg.get("task_type", "incident"),
            trigger_source="rule_engine",
            title=title,
            priority=cfg.get("priority", 1),
            equipment_code=rule.equipment_code,
            site_id=rule.site_id,
            description=cfg.get("description", f"Auto-created by rule '{rule.name}'"),
            deadline=datetime.utcnow() + timedelta(days=cfg.get("deadline_days", 7)),
            creator=f"rule:{rule.id}",
            responsible_user_id=rule.executor_bitrix_id,
            responsible_name=rule.executor_name,
            alarm_name=alarm.get("alarm_name"),
        )

    async def _action_notify(self, rule: ScadaRule, cfg: dict, context: dict) -> None:
        """Send notification via Bitrix24 chat."""
        from services.task_manager.resilient_api import resilient_b24_call

        template = cfg.get("message_template", "Rule '{name}' triggered")
        message = template.format(
            name=rule.name,
            equipment=rule.equipment_code or "N/A",
            **{k: v for k, v in context.items() if isinstance(v, (str, int, float))},
        )

        if rule.executor_bitrix_id:
            await resilient_b24_call(
                "imbot.message.add",
                {
                    "BOT_ID": settings.BITRIX24_BOT_ID,
                    "DIALOG_ID": str(rule.executor_bitrix_id),
                    "MESSAGE": message,
                },
                self.redis,
            )

    async def _notify_watchers(self, rule: ScadaRule, context: dict) -> None:
        """Notify each watcher about rule trigger."""
        from services.task_manager.resilient_api import resilient_b24_call

        message = f"[auto] Rule '{rule.name}' triggered for {rule.equipment_code or 'N/A'}"

        for watcher in (rule.watchers or []):
            bitrix_id = watcher.get("bitrix_id")
            if bitrix_id:
                try:
                    await resilient_b24_call(
                        "imbot.message.add",
                        {
                            "BOT_ID": settings.BITRIX24_BOT_ID,
                            "DIALOG_ID": str(bitrix_id),
                            "MESSAGE": message,
                        },
                        self.redis,
                    )
                except Exception as e:
                    logger.warning("Failed to notify watcher %s: %s", bitrix_id, e)

    async def _log_decision(self, rule: ScadaRule, context: dict) -> None:
        """Log rule trigger to sanek_decision_log."""
        from models.task_manager import SanekDecisionLog

        try:
            async with async_session() as session:
                entry = SanekDecisionLog(
                    decision_type="rule_triggered",
                    decision_data={
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "trigger_type": rule.trigger_type,
                        "action_type": rule.action_type,
                        "context": {k: str(v)[:200] for k, v in context.items()},
                    },
                    reasoning=f"Rule '{rule.name}' matched",
                    triggered_by="rule_engine",
                )
                session.add(entry)
                await session.commit()
        except Exception as e:
            logger.warning("Failed to log decision for rule %d: %s", rule.id, e)

    # ── Schedule trigger ──────────────────────────────────────────
    async def check_schedule_rules(self) -> list[int]:
        """Check schedule-type rules and trigger if interval elapsed."""
        triggered: list[int] = []
        now = datetime.utcnow()

        async with async_session() as session:
            stmt = (
                select(ScadaRule)
                .where(ScadaRule.trigger_type == "schedule", ScadaRule.is_active.is_(True))
            )
            rules = (await session.execute(stmt)).scalars().all()

            for rule in rules:
                cfg = rule.trigger_config or {}
                interval_hours = cfg.get("interval_hours") or (cfg.get("interval_days", 1) * 24)

                if rule.last_triggered_at:
                    elapsed_hours = (now - rule.last_triggered_at).total_seconds() / 3600
                    if elapsed_hours < interval_hours:
                        continue

                await self.execute_action(rule, context={"schedule": True}, session=session)
                triggered.append(rule.id)

            if triggered:
                await session.commit()

        return triggered

    # ── Hours threshold trigger ───────────────────────────────────
    async def check_hours_rules(self) -> list[int]:
        """Check hours_threshold rules against device running_hours from Redis."""
        triggered: list[int] = []

        async with async_session() as session:
            stmt = (
                select(ScadaRule)
                .where(ScadaRule.trigger_type == "hours_threshold", ScadaRule.is_active.is_(True))
            )
            rules = (await session.execute(stmt)).scalars().all()

            for rule in rules:
                cfg = rule.trigger_config or {}
                interval_hours = cfg.get("interval_hours")
                if not interval_hours:
                    continue

                # Get running hours from Redis
                equipment = rule.equipment_code
                if not equipment:
                    continue

                try:
                    hours_key = f"running_hours:{equipment}"
                    raw = await self.redis.get(hours_key)
                    if raw is None:
                        continue
                    current_hours = float(raw)
                except (ValueError, TypeError):
                    continue

                # Check if hours crossed a threshold boundary
                if current_hours > 0 and current_hours % interval_hours < 1:
                    # Cooldown
                    now = datetime.utcnow()
                    if rule.last_triggered_at:
                        elapsed = (now - rule.last_triggered_at).total_seconds() / 3600
                        if elapsed < interval_hours:
                            continue

                    context = {
                        "equipment_code": equipment,
                        "running_hours": current_hours,
                        "maintenance_type": cfg.get("maintenance_type", "scheduled"),
                    }
                    await self.execute_action(rule, context=context, session=session)
                    triggered.append(rule.id)

            if triggered:
                await session.commit()

        return triggered
