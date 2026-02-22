"""Bitrix24 integration module — fully isolated.

Entry point: Bitrix24Module. Creates and coordinates all sub-services.
Can be removed entirely without affecting core SCADA functionality.
"""
import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import settings
from services.bitrix24.client import Bitrix24Client
from services.bitrix24.equipment import EquipmentSync
from services.bitrix24.tasks import TaskCreator
from services.bitrix24.events import EventListener

logger = logging.getLogger("scada.bitrix24")


class Bitrix24Module:
    """Main orchestrator. Fully isolated — can be deleted without consequences."""

    def __init__(
        self,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.redis = redis
        self.session_factory = session_factory

        self.client = Bitrix24Client(
            settings.BITRIX24_WEBHOOK_URL,
            settings.BITRIX24_RATE_LIMIT,
        )
        self.equipment_sync = EquipmentSync(self.client, redis)
        self.task_creator = TaskCreator(
            self.client, redis, session_factory, self.equipment_sync,
        )
        self.event_listener = EventListener(
            redis, self.task_creator, self.equipment_sync,
        )

        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start all sub-services."""
        logger.info("Bitrix24 module starting...")

        # Test connection
        conn = await self.client.test_connection()
        if conn.get("success"):
            logger.info("Bitrix24 connection OK")
        else:
            logger.warning("Bitrix24 connection failed: %s", conn.get("error"))

        # Initial equipment sync
        await self.equipment_sync.initial_sync()

        # Start background tasks
        self._tasks = [
            asyncio.create_task(
                self.equipment_sync.run_periodic(),
                name="b24_equipment_sync",
            ),
            asyncio.create_task(
                self.event_listener.listen(),
                name="b24_event_listener",
            ),
            asyncio.create_task(
                self.task_creator.sync_status_loop(),
                name="b24_task_status_sync",
            ),
        ]

        logger.info(
            "Bitrix24 module started: %d equipment cached, listening on 3 channels",
            self.equipment_sync.cached_count,
        )

    async def stop(self) -> None:
        """Stop all sub-services gracefully."""
        logger.info("Bitrix24 module stopping...")
        self.event_listener.stop()

        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self.client.close()
        logger.info("Bitrix24 module stopped")
