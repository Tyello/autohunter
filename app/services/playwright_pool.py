from __future__ import annotations

import os
import queue
import random
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

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


class _Job:
    __slots__ = ("name", "args", "kwargs", "done", "result", "exc", "tb")

    def __init__(self, name: str, args: tuple, kwargs: dict):
        self.name = name
        self.args = args
        self.kwargs = kwargs
        self.done = threading.Event()
        self.result: Any = None
        self.exc: Optional[BaseException] = None
        self.tb: Optional[str] = None

    def set_result(self, v: Any) -> None:
        self.result = v
        self.done.set()

    def set_exc(self, e: BaseException) -> None:
        self.exc = e
        self.tb = traceback.format_exc()
        self.done.set()


class _PlaywrightWorker(threading.Thread):
    """
    Dedicated worker thread that owns Playwright Sync API objects.

    Why:
    - Playwright Sync is NOT safe to use across threads/greenlets.
    - Serializing all browser operations in 1 thread eliminates
      "cannot switch to a different thread"/greenlet crashes.
    """

    def __init__(self) -> None:
        super().__init__(name="PlaywrightWorker", daemon=True)
        self.q: "queue.Queue[_Job]" = queue.Queue()
        self._ready = threading.Event()
        self._stop = False

        # Owned by this thread only
        self._p = None
        self._started = False
        self._browsers: Dict[str, object] = {}
        self._contexts: Dict[Tuple[str, str], object] = {}
        self._last_error: Optional[str] = None

    # ---------------------------
    # Thread lifecycle
    # ---------------------------
    def run(self) -> None:
        try:
            try:
                from playwright.sync_api import sync_playwright
            except Exception as e:  # pragma: no cover
                self._last_error = (
                    "Playwright not installed. Run: pip install playwright && playwright install chromium"
                )
                raise

            self._p = sync_playwright().start()
            self._started = True
        except Exception:
            self._ready.set()
            return

        self._ready.set()

        while True:
            job = self.q.get()
            if job.name == "__stop__":
                job.set_result(True)
                break

            try:
                fn = getattr(self, f"_do_{job.name}")
            except AttributeError:
                job.set_exc(RuntimeError(f"Unknown Playwright job: {job.name}"))
                continue

            try:
                job.set_result(fn(*job.args, **job.kwargs))
            except Exception as e:
                self._last_error = traceback.format_exc()
                job.set_exc(e)

        self._cleanup()

    def _cleanup(self) -> None:
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
            if self._p is not None:
                self._p.stop()
        except Exception:
            pass

        self._p = None
        self._started = False

    # ---------------------------
    # Browser helpers (thread-owned)
    # ---------------------------
    def _storage_path(self, proxy_key: str, source: str) -> str:
        base = Path(settings.playwright_storage_dir or ".data/playwright")
        base.mkdir(parents=True, exist_ok=True)
        safe_proxy = proxy_key.replace(":", "_").replace("/", "_")
        safe_source = source.replace(":", "_").replace("/", "_")
        return str(base / f"storage_{safe_source}__{safe_proxy}.json")

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

        launch_kwargs: dict = {"headless": headless}
        if proxy_server:
            launch_kwargs["proxy"] = {"server": proxy_server}

        b = self._p.chromium.launch(**launch_kwargs)
        self._browsers[key] = b
        return b

    def _get_or_create_context(self, *, proxy_server: Optional[str], source: str) -> object:
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

    def _block_heavy_resources(self, page: object) -> None:
        def _route(route):
            rtype = route.request.resource_type
            if rtype in ("image", "media", "font"):
                return route.abort()
            return route.continue_()

        page.route("**/*", _route)

    # ---------------------------
    # Jobs (executed in worker thread)
    # ---------------------------
    def _do_stats(self) -> dict:
        return {
            "started": self._started,
            "browsers": len(self._browsers),
            "contexts": len(self._contexts),
            "proxy_keys": list(self._browsers.keys())[:10],
            "last_error": (self._last_error[:500] if self._last_error else None),
        }

    def _do_fetch(
        self,
        url: str,
        *,
        source: str,
        proxy_server: Optional[str],
        timeout_ms: int,
        wait_until: str,
        min_delay_ms: int,
        max_delay_ms: int,
    ) -> PoolFetchResult:
        # Small random delay to reduce patterns
        time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

        src = (source or "unknown").lower().strip() or "unknown"
        ctx = self._get_or_create_context(proxy_server=proxy_server, source=src)

        page = ctx.new_page()
        self._block_heavy_resources(page)

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

    def _do_fetch_json(
        self,
        url: str,
        *,
        source: str,
        proxy_server: Optional[str],
        timeout_ms: int,
        wait_until: str,
        json_url_predicate: Optional[Callable[[str, dict, int], bool]],
        min_delay_ms: int,
        max_delay_ms: int,
    ) -> PoolJsonFetchResult:
        """Navigate a page and capture a JSON response emitted during navigation.

        Intended for Next.js "_next/data" endpoints (OLX) and other SPA/XHR flows.
        """
        time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

        src = (source or "unknown").lower().strip() or "unknown"
        ctx = self._get_or_create_context(proxy_server=proxy_server, source=src)

        captured_data: Optional[dict] = None
        captured_url: str = ""

        def _default_pred(url_: str, headers_: dict, status_: int) -> bool:
            ct = (headers_.get("content-type") or "").lower()
            return status_ == 200 and "application/json" in ct

        pred = json_url_predicate or _default_pred

        page = ctx.new_page()
        self._block_heavy_resources(page)

        try:
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

            try:
                proxy_key = proxy_server or "__no_proxy__"
                storage_path = self._storage_path(proxy_key, src)
                ctx.storage_state(path=storage_path)
            except Exception:
                pass

        if not isinstance(captured_data, dict):
            raise RuntimeError("Browser JSON capture failed (no JSON response matched).")

        return PoolJsonFetchResult(data=captured_data, final_url=final_url, data_url=captured_url)


class PlaywrightPool:
    """
    Public facade. All Playwright Sync calls are executed inside a dedicated thread.

    This keeps the API stable for the rest of the codebase while making the
    implementation actually thread-safe for schedulers/bots.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._worker: Optional[_PlaywrightWorker] = None

    def start(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            w = _PlaywrightWorker()
            w.start()
            w._ready.wait(timeout=20)
            self._worker = w

            # If Playwright failed to start, surface a readable error
            if not w._started:
                err = w._last_error or "Playwright worker failed to start."
                raise RuntimeError(err)

    def close(self) -> None:
        with self._lock:
            if not self._worker or not self._worker.is_alive():
                return
            job = _Job("__stop__", (), {})
            self._worker.q.put(job)
        job.done.wait(timeout=10)

        with self._lock:
            try:
                self._worker.join(timeout=10)
            except Exception:
                pass
            self._worker = None

    def stats(self) -> dict:
        with self._lock:
            if not self._worker or not self._worker.is_alive():
                return {"started": False, "browsers": 0, "contexts": 0, "proxy_keys": [], "last_error": None}
            self.start()
            job = _Job("stats", (), {})
            self._worker.q.put(job)

        job.done.wait(timeout=5)
        if job.exc:
            raise job.exc
        return job.result

    def _call(self, name: str, *, hard_timeout_s: float, **kwargs):
        self.start()
        assert self._worker is not None

        job = _Job(name, (), kwargs)
        self._worker.q.put(job)

        if not job.done.wait(timeout=hard_timeout_s):
            raise TimeoutError(f"Playwright worker timed out waiting for job '{name}'.")

        if job.exc:
            # re-raise preserving original message; traceback is kept in stats().last_error
            raise job.exc

        return job.result

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
        hard_timeout_s = max(10.0, (timeout_ms / 1000.0) + 20.0)
        return self._call(
            "fetch",
            hard_timeout_s=hard_timeout_s,
            url=url,
            source=source,
            proxy_server=proxy_server,
            timeout_ms=timeout_ms,
            wait_until=wait_until,
            min_delay_ms=min_delay_ms,
            max_delay_ms=max_delay_ms,
        )

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
        hard_timeout_s = max(10.0, (timeout_ms / 1000.0) + 20.0)
        return self._call(
            "fetch_json",
            hard_timeout_s=hard_timeout_s,
            url=url,
            source=source,
            proxy_server=proxy_server,
            timeout_ms=timeout_ms,
            wait_until=wait_until,
            json_url_predicate=json_url_predicate,
            min_delay_ms=min_delay_ms,
            max_delay_ms=max_delay_ms,
        )


_POOL: Optional[PlaywrightPool] = None


def get_playwright_pool() -> PlaywrightPool:
    global _POOL
    if _POOL is None:
        _POOL = PlaywrightPool()
    return _POOL
