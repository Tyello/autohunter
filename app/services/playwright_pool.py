from __future__ import annotations

import os
import queue
import random
import threading
import time
import traceback
from collections import OrderedDict
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
    __slots__ = (
        "name",
        "args",
        "kwargs",
        "done",
        "result",
        "exc",
        "tb",
        "created_at",
        "started_at",
        "ended_at",
        "key",
    )

    def __init__(self, name: str, args: tuple, kwargs: dict, *, key: Optional[tuple] = None):
        self.name = name
        self.args = args
        self.kwargs = kwargs
        self.key = key
        self.done = threading.Event()
        self.result: Any = None
        self.exc: Optional[BaseException] = None
        self.tb: Optional[str] = None
        self.created_at = time.perf_counter()
        self.started_at: Optional[float] = None
        self.ended_at: Optional[float] = None

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
        max_jobs = int(getattr(settings, "playwright_queue_max_jobs", 25) or 25)
        self._queue_max_jobs = max(1, max_jobs)
        self.q: "queue.Queue[_Job]" = queue.Queue(maxsize=self._queue_max_jobs)
        self._ready = threading.Event()
        self._stop = False

        # Owned by this thread only
        self._p = None
        self._started = False
        self._browsers: Dict[str, object] = {}
        self._contexts: Dict[Tuple[str, str], object] = {}
        self._last_error: Optional[str] = None

        # Metrics (worker-side)
        self._jobs_done = 0
        self._jobs_failed = 0
        self._exec_ms_total = 0.0
        self._wait_ms_total = 0.0
        self._last_job: Optional[dict] = None

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
                # stop request; don't count as a real job
                job.started_at = time.perf_counter()
                job.ended_at = job.started_at
                job.set_result(True)
                break

            try:
                fn = getattr(self, f"_do_{job.name}")
            except AttributeError:
                job.started_at = time.perf_counter()
                job.ended_at = job.started_at
                job.set_exc(RuntimeError(f"Unknown Playwright job: {job.name}"))
                self._jobs_failed += 1
                continue

            job.started_at = time.perf_counter()
            try:
                job.set_result(fn(*job.args, **job.kwargs))
            except Exception as e:
                self._last_error = traceback.format_exc()
                job.set_exc(e)
                self._jobs_failed += 1
            finally:
                job.ended_at = time.perf_counter()
                # Update metrics (best-effort)
                try:
                    exec_ms = max(0.0, (job.ended_at - (job.started_at or job.ended_at)) * 1000.0)
                    wait_ms = max(0.0, ((job.started_at or job.ended_at) - job.created_at) * 1000.0)
                    self._jobs_done += 1
                    self._exec_ms_total += exec_ms
                    self._wait_ms_total += wait_ms
                    self._last_job = {
                        "name": job.name,
                        "exec_ms": int(exec_ms),
                        "wait_ms": int(wait_ms),
                        "key": (str(job.key)[:200] if job.key else None),
                    }
                except Exception:
                    pass

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
    jobs_done = int(self._jobs_done or 0)
    avg_exec = (self._exec_ms_total / jobs_done) if jobs_done else 0.0
    avg_wait = (self._wait_ms_total / jobs_done) if jobs_done else 0.0

    return {
        "started": self._started,
        "browsers": len(self._browsers),
        "contexts": len(self._contexts),
        "proxy_keys": list(self._browsers.keys())[:10],
        "last_error": (self._last_error[:500] if self._last_error else None),
        "queue_size": int(self.q.qsize()),
        "queue_max": int(getattr(self, "_queue_max_jobs", 0) or 0),
        "jobs_done": jobs_done,
        "jobs_failed": int(self._jobs_failed or 0),
        "avg_exec_ms": int(avg_exec),
        "avg_wait_ms": int(avg_wait),
        "last_job": self._last_job,
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

    Added for scale:
    - Bounded queue (protects Raspberry Pi RAM)
    - In-flight dedupe: if same request is already queued/running, callers "join" instead of enqueueing duplicates
    - Short TTL cache (default: only for fetch_json) to collapse bursts across users
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._worker: Optional[_PlaywrightWorker] = None

        # In-flight dedupe (key -> job)
        self._pending: Dict[tuple, _Job] = {}

        # Short TTL cache (LRU): key -> (expires_at_monotonic, result)
        self._cache: "OrderedDict[tuple, tuple[float, Any]]" = OrderedDict()

        # Metrics (facade-side)
        self._m_submitted = 0
        self._m_queue_full = 0
        self._m_dedupe_joins = 0
        self._m_cache_hits = 0

    # ---------------------------
    # Internal helpers
    # ---------------------------
    def _cfg_queue_max(self) -> int:
        return int(getattr(settings, "playwright_queue_max_jobs", 25) or 25)

    def _cfg_dedupe(self) -> bool:
        return bool(getattr(settings, "playwright_dedupe_inflight", True))

    def _cfg_cache_ttl(self) -> int:
        return int(getattr(settings, "playwright_cache_ttl_seconds", 30) or 0)

    def _cfg_cache_max(self) -> int:
        return int(getattr(settings, "playwright_cache_max_entries", 16) or 0)

    def _cache_enabled(self, name: str) -> bool:
        # HTML can be huge; keep caching conservative by default.
        return name == "fetch_json" and self._cfg_cache_ttl() > 0 and self._cfg_cache_max() > 0

    def _make_key(self, name: str, **kwargs) -> tuple:
        # Normalize fields we care about for dedupe/caching.
        # NOTE: json_url_predicate may be a lambda/unhashable; we only differentiate "custom vs default".
        pred = kwargs.get("json_url_predicate", None)
        pred_flag = 1 if pred is not None else 0

        return (
            name,
            kwargs.get("url"),
            (kwargs.get("source") or "").lower().strip(),
            kwargs.get("proxy_server") or "",
            kwargs.get("timeout_ms"),
            kwargs.get("wait_until"),
            pred_flag,
        )

    def _cache_purge(self) -> None:
        now = time.perf_counter()
        # Drop expired
        for k in list(self._cache.keys()):
            exp, _ = self._cache.get(k, (0.0, None))
            if exp <= now:
                self._cache.pop(k, None)

        # Enforce max entries (LRU by insertion order)
        max_entries = self._cfg_cache_max()
        while max_entries > 0 and len(self._cache) > max_entries:
            self._cache.popitem(last=False)

    def _cache_get(self, key: tuple) -> Any | None:
        if not self._cache:
            return None
        now = time.perf_counter()
        v = self._cache.get(key)
        if not v:
            return None
        exp, res = v
        if exp <= now:
            self._cache.pop(key, None)
            return None
        # Refresh LRU
        try:
            self._cache.move_to_end(key, last=True)
        except Exception:
            pass
        return res

    def _cache_set(self, key: tuple, res: Any) -> None:
        ttl = self._cfg_cache_ttl()
        if ttl <= 0:
            return
        self._cache[key] = (time.perf_counter() + float(ttl), res)
        self._cache_purge()

    # ---------------------------
    # Lifecycle
    # ---------------------------
    def start(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            w = _PlaywrightWorker()
            w.start()
            w._ready.wait(timeout=20)
            self._worker = w

            if not w._started:
                err = w._last_error or "Playwright worker failed to start."
                raise RuntimeError(err)

    def close(self) -> None:
        with self._lock:
            if not self._worker or not self._worker.is_alive():
                return
            job = _Job("__stop__", (), {}, key=("__stop__",))
            # stop should not be dropped; block briefly
            try:
                self._worker.q.put(job, timeout=2)
            except Exception:
                # best-effort
                return

        job.done.wait(timeout=10)

        with self._lock:
            try:
                self._worker.join(timeout=10)
            except Exception:
                pass
            self._worker = None
            self._pending.clear()
            self._cache.clear()

    # ---------------------------
    # Introspection
    # ---------------------------
    def stats(self) -> dict:
        with self._lock:
            base = {
                "started": False,
                "browsers": 0,
                "contexts": 0,
                "proxy_keys": [],
                "last_error": None,
                "queue_size": 0,
                "queue_max": self._cfg_queue_max(),
                "jobs_done": 0,
                "jobs_failed": 0,
                "avg_exec_ms": 0,
                "avg_wait_ms": 0,
                "last_job": None,
                "pending_inflight": len(self._pending),
                "cache_entries": len(self._cache),
                "submitted": self._m_submitted,
                "queue_full_rejects": self._m_queue_full,
                "dedupe_joins": self._m_dedupe_joins,
                "cache_hits": self._m_cache_hits,
            }

            if not self._worker or not self._worker.is_alive():
                return base

            # Ask worker for its own stats
            job = _Job("stats", (), {}, key=("stats",))
            try:
                self._worker.q.put(job, timeout=1)
            except Exception:
                return base

        job.done.wait(timeout=5)
        if job.exc:
            return base

        st = job.result or {}
        if not isinstance(st, dict):
            return base

        # Merge
        base.update(st)
        base["pending_inflight"] = len(self._pending)
        base["cache_entries"] = len(self._cache)
        base["submitted"] = self._m_submitted
        base["queue_full_rejects"] = self._m_queue_full
        base["dedupe_joins"] = self._m_dedupe_joins
        base["cache_hits"] = self._m_cache_hits
        return base

    # ---------------------------
    # Core call path
    # ---------------------------
    def _call(self, name: str, *, hard_timeout_s: float, **kwargs):
        self.start()
        assert self._worker is not None

        key = self._make_key(name, **kwargs)

        # Fast path: cache
        with self._lock:
            if self._cache_enabled(name):
                self._cache_purge()
                cached = self._cache_get(key)
                if cached is not None:
                    self._m_cache_hits += 1
                    return cached

            # In-flight dedupe
            if self._cfg_dedupe():
                existing = self._pending.get(key)
                if existing is not None:
                    self._m_dedupe_joins += 1
                    job = existing
                else:
                    job = _Job(name, (), kwargs, key=key)
                    self._pending[key] = job
                    self._m_submitted += 1
                    try:
                        self._worker.q.put_nowait(job)
                    except queue.Full:
                        self._m_queue_full += 1
                        # rollback pending
                        self._pending.pop(key, None)
                        raise RuntimeError(
                            f"Playwright queue is full (max={self._cfg_queue_max()}). "
                            "Reduce concurrency / increase interval / move browser worker to a stronger host."
                        )
            else:
                job = _Job(name, (), kwargs, key=key)
                self._m_submitted += 1
                try:
                    self._worker.q.put_nowait(job)
                except queue.Full:
                    self._m_queue_full += 1
                    raise RuntimeError(
                        f"Playwright queue is full (max={self._cfg_queue_max()}). "
                        "Reduce concurrency / increase interval / move browser worker to a stronger host."
                    )

        # Wait outside lock
        if not job.done.wait(timeout=hard_timeout_s):
            # Ensure pending is cleaned
            with self._lock:
                if self._pending.get(key) is job:
                    self._pending.pop(key, None)
            raise TimeoutError(f"Playwright worker timed out waiting for job '{name}'.")

        # Clean pending & cache
        with self._lock:
            if self._pending.get(key) is job:
                self._pending.pop(key, None)
            if (job.exc is None) and self._cache_enabled(name):
                try:
                    self._cache_set(key, job.result)
                except Exception:
                    pass

        if job.exc:
            raise job.exc

        return job.result

    # ---------------------------
    # Public API
    # ---------------------------
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
