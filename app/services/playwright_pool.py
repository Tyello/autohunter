from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from app.core.settings import settings


@dataclass
class PoolFetchResult:
    html: str
    final_url: str


@dataclass
class PoolJsonFetchResult:
    """Result for JSON capture inside a browser context."""

    data: dict
    final_url: str
    data_url: str


class PlaywrightPool:
    """Synchronous Playwright pool with stickiness.

    Goals:
    - Keep 1 Playwright instance alive
    - Reuse Chromium browsers (keyed by proxy)
    - Reuse BrowserContexts (keyed by (proxy, source)) for cookie/session stickiness

    This is critical for:
    - OLX (reduces challenges)
    - Low-power hosts (Raspberry Pi 3)
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._started = False
        self._p = None
        self._browsers: Dict[str, object] = {}
        self._contexts: Dict[Tuple[str, str], object] = {}

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            try:
                from playwright.sync_api import sync_playwright
            except Exception as e:  # pragma: no cover
                raise RuntimeError(
                    "Playwright not installed. Run: pip install playwright && playwright install chromium"
                ) from e

            self._p = sync_playwright().start()
            self._started = True

    def close(self) -> None:
        with self._lock:
            if not self._started:
                return

            # Close contexts first
            for ctx in list(self._contexts.values()):
                try:
                    ctx.close()
                except Exception:
                    pass
            self._contexts.clear()

            for b in list(self._browsers.values()):
                try:
                    b.close()
                except Exception:
                    pass
            self._browsers.clear()

            try:
                self._p.stop()
            except Exception:
                pass
            self._p = None
            self._started = False

    def stats(self) -> dict:
        with self._lock:
            return {
                "started": self._started,
                "browsers": len(self._browsers),
                "contexts": len(self._contexts),
                "proxy_keys": list(self._browsers.keys())[:10],
            }

    def _get_or_create_browser(self, proxy_server: Optional[str]) -> object:
        assert self._p is not None
        key = proxy_server or "__no_proxy__"
        b = self._browsers.get(key)
        if b is not None:
            return b

        # Headless from Settings (env override still allowed)
        headless_env = os.getenv("PLAYWRIGHT_HEADLESS")
        if headless_env is None:
            headless = bool(settings.playwright_headless)
        else:
            headless = headless_env.lower() not in ("0", "false", "no")

        launch_kwargs = {"headless": headless}
        if proxy_server:
            launch_kwargs["proxy"] = {"server": proxy_server}

        b = self._p.chromium.launch(**launch_kwargs)
        self._browsers[key] = b
        return b

    def _storage_path(self, proxy_key: str, source: str) -> str:
        base = Path(settings.playwright_storage_dir or ".data/playwright")
        base.mkdir(parents=True, exist_ok=True)
        safe_proxy = proxy_key.replace(":", "_").replace("/", "_")
        safe_source = source.replace(":", "_").replace("/", "_")
        return str(base / f"storage_{safe_source}__{safe_proxy}.json")

    def _get_or_create_context(self, *, proxy_server: Optional[str], source: str) -> object:
        self.start()
        assert self._p is not None

        proxy_key = proxy_server or "__no_proxy__"
        key = (proxy_key, source)
        ctx = self._contexts.get(key)
        if ctx is not None:
            return ctx

        browser = self._get_or_create_browser(proxy_server)

        # Keep a stable UA per (proxy, source)
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        ]
        ua = random.choice(user_agents)

        storage_path = self._storage_path(proxy_key, source)
        storage_state = storage_path if os.path.exists(storage_path) else None

        ctx = browser.new_context(
            user_agent=ua,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": random.choice([1280, 1366, 1440]), "height": random.choice([720, 800, 900])},
            storage_state=storage_state,
        )

        self._contexts[key] = ctx
        return ctx

    def fetch(
        self,
        url: str,
        *,
        source: str,
        proxy_server: Optional[str] = None,
        timeout_ms: int = 30000,
        wait_until: str = "networkidle",
        min_delay_ms: int = 250,
        max_delay_ms: int = 900,
    ) -> PoolFetchResult:
        # Small random delay to reduce patterns
        time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

        src = (source or "unknown").lower().strip() or "unknown"

        with self._lock:
            ctx = self._get_or_create_context(proxy_server=proxy_server, source=src)

        # Block heavy resources
        def _route(route):
            rtype = route.request.resource_type
            if rtype in ("image", "media", "font"):
                return route.abort()
            return route.continue_()

        page = ctx.new_page()
        page.route("**/*", _route)

        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            page.wait_for_timeout(500)
            html = page.content()
            final_url = page.url
        finally:
            try:
                page.close()
            except Exception:
                pass

            # Persist cookies/session for stickiness across restarts
            try:
                proxy_key = proxy_server or "__no_proxy__"
                storage_path = self._storage_path(proxy_key, src)
                ctx.storage_state(path=storage_path)
            except Exception:
                pass

        return PoolFetchResult(html=html, final_url=final_url)


    def fetch_json(
        self,
        url: str,
        *,
        source: str,
        proxy_server: Optional[str] = None,
        timeout_ms: int = 30000,
        wait_until: str = "domcontentloaded",
        json_url_predicate: Optional[Callable[[str, dict, int], bool]] = None,
        min_delay_ms: int = 250,
        max_delay_ms: int = 900,
    ) -> PoolJsonFetchResult:
        """Navigate a page and capture a JSON response emitted during navigation.

        This is intended for Next.js "_next/data" endpoints (OLX) and other SPA/XHR flows.
        It keeps everything inside the browser context (cookies, TLS fingerprint), while
        avoiding the cost of parsing/rendering heavy DOM content.
        """

        # Small random delay to reduce patterns
        time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

        src = (source or "unknown").lower().strip() or "unknown"

        with self._lock:
            ctx = self._get_or_create_context(proxy_server=proxy_server, source=src)

        def _route(route):
            rtype = route.request.resource_type
            if rtype in ("image", "media", "font"):
                return route.abort()
            return route.continue_()

        page = ctx.new_page()
        page.route("**/*", _route)

        captured_data: Optional[dict] = None
        captured_url: str = ""

        def _default_pred(url_: str, headers_: dict, status_: int) -> bool:
            ct = (headers_.get("content-type") or "").lower()
            return status_ == 200 and "application/json" in ct

        pred = json_url_predicate or _default_pred

        try:
            # Expect a JSON response during navigation
            with page.expect_response(lambda r: pred(r.url, r.headers, r.status), timeout=timeout_ms) as resp_info:
                page.goto(url, wait_until=wait_until, timeout=timeout_ms)

            resp = resp_info.value
            captured_url = resp.url
            captured_data = resp.json()
            final_url = page.url

        finally:
            try:
                page.close()
            except Exception:
                pass

            # Persist cookies/session for stickiness across restarts
            try:
                proxy_key = proxy_server or "__no_proxy__"
                storage_path = self._storage_path(proxy_key, src)
                ctx.storage_state(path=storage_path)
            except Exception:
                pass

        if not isinstance(captured_data, dict):
            raise RuntimeError("Browser JSON capture failed (no JSON response matched).")

        return PoolJsonFetchResult(data=captured_data, final_url=final_url, data_url=captured_url)


_POOL: Optional[PlaywrightPool] = None


def get_playwright_pool() -> PlaywrightPool:
    global _POOL
    if _POOL is None:
        _POOL = PlaywrightPool()
    return _POOL
