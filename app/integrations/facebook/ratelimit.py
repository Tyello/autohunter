from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque


class TTLRateLimiter:
    def __init__(self, max_hits: int, ttl_seconds: int) -> None:
        self.max_hits = max_hits
        self.ttl_seconds = ttl_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str) -> bool:
        now = time.time()
        async with self._lock:
            q = self._events[key]
            while q and (now - q[0]) > self.ttl_seconds:
                q.popleft()
            if len(q) >= self.max_hits:
                return False
            q.append(now)
            return True
