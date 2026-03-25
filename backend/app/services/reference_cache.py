"""In-memory TTL cache для справочных данных."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional


class ReferenceCache:
    def __init__(self, ttl_seconds: int = 600):
        self.ttl = ttl_seconds
        self._data: dict[str, Any] = {}
        self._ts: dict[str, datetime] = {}

    def get(self, key: str) -> Optional[Any]:
        if key not in self._data:
            return None
        if (datetime.utcnow() - self._ts[key]).total_seconds() > self.ttl:
            del self._data[key]
            del self._ts[key]
            return None
        return self._data[key]

    def set(self, key: str, value: Any):
        self._data[key] = value
        self._ts[key] = datetime.utcnow()

    def invalidate(self, key: Optional[str] = None):
        if key:
            self._data.pop(key, None)
            self._ts.pop(key, None)
        else:
            self._data.clear()
            self._ts.clear()


topology_cache = ReferenceCache(ttl_seconds=300)
definitions_cache = ReferenceCache(ttl_seconds=600)
learned_context_cache = ReferenceCache(ttl_seconds=600)
