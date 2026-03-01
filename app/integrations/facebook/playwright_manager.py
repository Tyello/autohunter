from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from app.core.settings import settings


class FBPlaywrightManager:
    def __init__(self) -> None:
        self._global_sem = asyncio.Semaphore(max(1, int(getattr(settings, "fb_max_parallel_browsers", 1) or 1)))
        self._user_locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def _get_user_lock(self, user_id: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._user_locks.get(user_id)
            if lock is None:
                lock = asyncio.Lock()
                self._user_locks[user_id] = lock
            return lock

    @asynccontextmanager
    async def open_context(self, *, user_id: str, profile_dir: Path, headless: bool, correlation_id: str) -> AsyncIterator[Any]:
        from playwright.async_api import async_playwright

        user_lock = await self._get_user_lock(user_id)
        async with self._global_sem:
            async with user_lock:
                async with async_playwright() as p:
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=str(profile_dir),
                        headless=headless,
                        args=["--no-sandbox", "--disable-dev-shm-usage"],
                    )
                    try:
                        yield context
                    finally:
                        await context.close()


fb_playwright_manager = FBPlaywrightManager()
