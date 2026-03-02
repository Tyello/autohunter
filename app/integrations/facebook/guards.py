from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class FBUserLock:
    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._active: set[str] = set()

    @asynccontextmanager
    async def acquire(self, user_id: str):
        async with self._guard:
            if user_id in self._active:
                yield False
                return
            self._active.add(user_id)
        try:
            yield True
        finally:
            async with self._guard:
                self._active.discard(user_id)


fb_user_lock = FBUserLock()
