"""Bitrix24 HTTP client with rate limiting and retry.

Responsibilities:
- HTTP requests to webhook URL
- Rate limiting (max 2 req/sec via semaphore + sleep)
- Retry on errors (3 attempts, exponential backoff)
- Logging all API calls
- Bitrix24 error handling

Does NOT know about business logic.
"""
import asyncio
import logging
import time

import httpx

logger = logging.getLogger("scada.bitrix24.client")


class Bitrix24Error(Exception):
    """Bitrix24 API error."""
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


class Bitrix24AuthError(Bitrix24Error):
    """Fatal auth error — module should be disabled."""
    pass


class Bitrix24Client:

    def __init__(self, webhook_url: str, rate_limit: float = 2.0):
        self.base_url = webhook_url.rstrip("/")
        self._semaphore = asyncio.Semaphore(1)
        self._rate_interval = 1.0 / rate_limit if rate_limit > 0 else 0.5
        self._last_request_time: float = 0.0
        self._client = httpx.AsyncClient(timeout=15.0)
        self.is_connected: bool = False

    async def call(self, method: str, params: dict | None = None) -> dict:
        """Single API call with rate limiting and retry."""
        url = f"{self.base_url}/{method}.json"
        last_exc = None

        for attempt in range(3):
            async with self._semaphore:
                # Rate limiting
                now = time.monotonic()
                wait = self._rate_interval - (now - self._last_request_time)
                if wait > 0:
                    await asyncio.sleep(wait)

                try:
                    resp = await self._client.post(url, json=params or {})
                    self._last_request_time = time.monotonic()
                    resp.raise_for_status()
                    data = resp.json()

                    # Check Bitrix24 errors
                    if "error" in data:
                        error_code = data.get("error", "")
                        error_msg = data.get("error_description", str(data))

                        if error_code == "QUERY_LIMIT_EXCEEDED":
                            logger.warning("B24 rate limit hit, retry in 1s")
                            await asyncio.sleep(1.0)
                            continue

                        if error_code in ("INVALID_TOKEN", "NO_AUTH_FOUND",
                                          "expired_token"):
                            self.is_connected = False
                            raise Bitrix24AuthError(error_code, error_msg)

                        raise Bitrix24Error(error_code, error_msg)

                    self.is_connected = True
                    return data

                except Bitrix24AuthError:
                    raise
                except Bitrix24Error:
                    raise
                except httpx.HTTPStatusError as exc:
                    last_exc = exc
                    if exc.response.status_code >= 500:
                        backoff = 2 ** attempt
                        logger.warning(
                            "B24 HTTP %d, retry %d/3 in %ds",
                            exc.response.status_code, attempt + 1, backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    raise
                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    last_exc = exc
                    backoff = 2 ** attempt
                    logger.warning(
                        "B24 connection error: %s, retry %d/3 in %ds",
                        exc, attempt + 1, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

        self.is_connected = False
        raise last_exc or Exception("Bitrix24 call failed after 3 retries")

    async def batch(self, calls: dict[str, str]) -> dict:
        """Batch API call (up to 50 methods in one request)."""
        return await self.call("batch", {"halt": 0, "cmd": calls})

    async def test_connection(self) -> dict:
        """Test connection via profile method."""
        try:
            result = await self.call("profile")
            self.is_connected = True
            return {"success": True, "data": result.get("result", {})}
        except Exception as exc:
            self.is_connected = False
            return {"success": False, "error": str(exc)}

    async def create_task(self, fields: dict) -> dict:
        """Create a task via tasks.task.add."""
        result = await self.call("tasks.task.add", {"fields": fields})
        return result.get("result", {})

    async def add_checklist_item(self, task_id: int, title: str, is_complete: bool = False) -> dict:
        """Add checklist item via task.checklistitem.add."""
        return await self.call("task.checklistitem.add", {
            "TASKID": task_id,
            "FIELDS": {"TITLE": title, "IS_COMPLETE": "Y" if is_complete else "N"},
        })

    async def get_task(self, task_id: int) -> dict | None:
        """Get task details via tasks.task.get."""
        try:
            result = await self.call("tasks.task.get", {"taskId": task_id})
            return result.get("result", {}).get("task", {})
        except Bitrix24Error:
            return None

    async def get_list_elements(
        self, iblock_type_id: str, iblock_id: int,
    ) -> list[dict]:
        """Get all elements from a Bitrix24 list (Universal List)."""
        all_elements: list[dict] = []
        start = 0

        while True:
            result = await self.call("lists.element.get", {
                "IBLOCK_TYPE_ID": iblock_type_id,
                "IBLOCK_ID": iblock_id,
                "start": start,
            })
            elements = result.get("result", [])
            if not elements:
                break
            all_elements.extend(elements)
            # Bitrix24 pagination: 50 items per page
            if len(elements) < 50:
                break
            start += 50

        return all_elements

    async def get_user(self, user_id: int) -> dict | None:
        """Get user info via user.get."""
        try:
            result = await self.call("user.get", {"ID": user_id})
            users = result.get("result", [])
            return users[0] if users else None
        except Bitrix24Error:
            return None

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
