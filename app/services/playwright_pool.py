from __future__ import annotations

import os
import queue
import random
import re
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


@dataclass
class _Job:
    name: str
    kwargs: dict
    done: threading.Event
    result: Any = None
    exc: Optional[BaseException] = None
    tb: str = ""


class _PlaywrightCore:
    """Must be used ONLY inside the worker thread."""

    def __init__(self) -> None:
        self._booted = False
        self._p = None
        self._browsers: Dict[str, Any] = {}                # proxy_key -> Browser
        self._contexts: Dict[Tuple[str, str], Any] = {}    # (proxy_key, source) -> BrowserContext
        self._ctx_last_used: Dict[Tuple[str, str], float] = {}
        self._evicted_contexts: int = 0

    def start(self) -> None:
        if self._booted:
            return
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # pragma: no cover
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && python -m playwright install chromium"
            ) from e
        self._p = sync_playwright().start()
        self._booted = True

    def close(self) -> None:
        if not self._booted:
            return
        # contexts
        for ctx in list(self._contexts.values()):
            try:
                ctx.close()
            except Exception:
                pass
        self._contexts.clear()
        # browsers
        for b in list(self._browsers.values()):
            try:
                b.close()
            except Exception:
                pass
        self._browsers.clear()
        # playwright
        try:
            self._p.stop()
        except Exception:
            pass
        self._p = None
        self._booted = False

    def stats(self) -> dict:
        # evict idle contexts before reporting
        try:
            self._cleanup_contexts()
        except Exception:
            pass
        return {
            "started": self._booted,
            "browsers": len(self._browsers),
            "contexts": len(self._contexts),
            "proxy_keys": list(self._browsers.keys())[:10],
            "evicted_contexts": self._evicted_contexts,
            "max_contexts": int(getattr(settings, 'playwright_max_contexts', 0) or 0),
            "context_ttl_s": int(getattr(settings, 'playwright_context_ttl_seconds', 0) or 0),
        }

    def _storage_path(self, proxy_key: str, source: str) -> str:
        base = Path(settings.playwright_storage_dir or ".data/playwright")
        base.mkdir(parents=True, exist_ok=True)
        safe_proxy = proxy_key.replace(":", "_").replace("/", "_")
        safe_source = source.replace(":", "_").replace("/", "_")
        return str(base / f"storage_{safe_source}__{safe_proxy}.json")

    def _block_heavy_resources(self, page: Any, *, source: str) -> None:
        """Block heavy resources to reduce RAM/CPU on small machines.

        IMPORTANT: Some anti-bot challenges rely on fetching images or other
        resources. For a small allowlist of "hostile" sources we do NOT block.
        """
        src = (source or "").strip().lower()
        allow_heavy = src in {"mobiauto", "facebook_marketplace", "icarros"}
        if allow_heavy:
            return

        # Best-effort: some page impls might not support route
        try:
            def _route(route):
                rtype = route.request.resource_type
                if rtype in ("image", "media", "font"):
                    return route.abort()
                return route.continue_()
            page.route("**/*", _route)
        except Exception:
            pass

    def _parse_missing_executable_path(self, msg: str) -> Optional[str]:
        # Example: "BrowserType.launch: Executable doesn't exist at /home/.../headless_shell ..."
        m = re.search(r"Executable doesn't exist at\s+([^\s]+)", msg)
        if not m:
            return None
        return m.group(1).strip()

    def _find_chromium_full_exe(self, ms_playwright_dir: Path, preferred_build: Optional[str]) -> Optional[str]:
        """
        Find .../chromium-<build>/chrome-linux/chrome, prefer matching build number when provided.
        """
        if not ms_playwright_dir.exists():
            return None

        candidates = []
        for p in ms_playwright_dir.glob("chromium-*/chrome-linux/chrome"):
            try:
                build = p.parts[-3]  # chromium-1200
            except Exception:
                build = ""
            candidates.append((build, p))

        if not candidates:
            return None

        # Prefer exact build match (chromium-1200)
        if preferred_build:
            for build, p in candidates:
                if build == preferred_build and p.exists():
                    return str(p)

        # Else pick newest by build number
        def _build_num(build: str) -> int:
            m = re.search(r"chromium-(\d+)", build)
            return int(m.group(1)) if m else -1

        candidates.sort(key=lambda bp: _build_num(bp[0]), reverse=True)
        for _, p in candidates:
            if p.exists():
                return str(p)
        return None

    def _launch_browser(self, *, proxy_server: Optional[str], headless: bool) -> Any:
        assert self._p is not None

        # Anti-detection hardening:
        # - Disable AutomationControlled blink feature.
        # - Remove Playwright's default "--enable-automation" flag.
        # Note: this is best-effort; some sites will still require proxy/cookies.
        launch_kwargs: Dict[str, Any] = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
            ],
            # Remove the automation flag when possible
            "ignore_default_args": ["--enable-automation"],
        }
        if proxy_server:
            launch_kwargs["proxy"] = {"server": proxy_server}

        try:
            return self._p.chromium.launch(**launch_kwargs)
        except Exception as e:
            msg = str(e)

            # Fallback for missing chromium_headless_shell executable
            if ("chromium_headless_shell" in msg) and ("Executable doesn't exist" in msg or "headless_shell" in msg):
                missing = self._parse_missing_executable_path(msg)
                if missing:
                    missing_path = Path(missing)
                    # .../ms-playwright/chromium_headless_shell-1200/chrome-linux/headless_shell
                    ms_dir = missing_path
                    # climb until ms-playwright
                    for _ in range(6):
                        if ms_dir.name == "ms-playwright":
                            break
                        ms_dir = ms_dir.parent
                    if ms_dir.name != "ms-playwright":
                        # fallback to HOME cache
                        ms_dir = Path.home() / ".cache" / "ms-playwright"

                    preferred_build = None
                    for part in missing_path.parts:
                        if part.startswith("chromium_headless_shell-") or part.startswith("chromium-"):
                            # normalize: chromium_headless_shell-1200 -> chromium-1200
                            preferred_build = "chromium-" + part.split("-")[-1]
                            break

                    full_exe = self._find_chromium_full_exe(ms_dir, preferred_build)
                    if full_exe:
                        launch_kwargs2 = dict(launch_kwargs)
                        launch_kwargs2["executable_path"] = full_exe
                        return self._p.chromium.launch(**launch_kwargs2)

            raise

    def _get_or_create_browser(self, proxy_server: Optional[str]) -> Any:
        self.start()
        assert self._p is not None

        key = proxy_server or "__no_proxy__"
        b = self._browsers.get(key)
        if b is not None:
            return b

        headless_env = os.getenv("PLAYWRIGHT_HEADLESS")
        if headless_env is None:
            headless = bool(settings.playwright_headless)
        else:
            headless = headless_env.lower() not in ("0", "false", "no")

        b = self._launch_browser(proxy_server=proxy_server, headless=headless)
        self._browsers[key] = b
        return b

    def _get_or_create_context(self, *, proxy_server: Optional[str], source: str) -> Any:
        # keep memory stable
        self._cleanup_contexts()
        src = (source or "unknown").lower().strip() or "unknown"
        proxy_key = proxy_server or "__no_proxy__"
        key = (proxy_key, src)
        ctx = self._contexts.get(key)
        if ctx is not None:
            self._ctx_last_used[key] = time.time()
            return ctx

        browser = self._get_or_create_browser(proxy_server)

        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        ]
        ua = random.choice(user_agents)

        storage_path = self._storage_path(proxy_key, src)
        storage_state = storage_path if os.path.exists(storage_path) else None

        ctx = browser.new_context(
            user_agent=ua,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": random.choice([1280, 1366, 1440]), "height": random.choice([720, 800, 900])},
            storage_state=storage_state,
        )

        # Basic stealth: hide webdriver and add minimal chrome object.
        # This helps with simple headless detections.
        try:
            ctx.add_init_script(
                """
                // Hide webdriver
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                // Minimal chrome object
                window.chrome = window.chrome || { runtime: {} };
                // Languages
                Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR','pt','en-US','en'] });
                """
            )
        except Exception:
            pass

        # Block heavy resources by default (speed + memory).
        # BUT: for some anti-bot challenges, blocking images/fonts can prevent the
        # challenge from completing. Keep them for these sources.
        try:
            heavy_ok_sources = {"mobiauto", "facebook_marketplace"}
            if src not in heavy_ok_sources:
                def _route(route):
                    rtype = route.request.resource_type
                    if rtype in ("image", "media", "font"):
                        return route.abort()
                    return route.continue_()
                ctx.route("**/*", _route)
        except Exception:
            pass

        self._contexts[key] = ctx
        self._ctx_last_used[key] = time.time()
        return ctx



    def _cleanup_contexts(self) -> None:
        """Evict idle contexts to keep RAM stable on small machines."""
        ttl = int(getattr(settings, "playwright_context_ttl_seconds", 0) or 0)
        max_ctx = int(getattr(settings, "playwright_max_contexts", 0) or 0)
        now = time.time()

        # TTL eviction
        if ttl > 0:
            stale = []
            for k, ts in list(self._ctx_last_used.items()):
                if (now - float(ts)) > ttl:
                    stale.append(k)
            for k in stale:
                ctx = self._contexts.pop(k, None)
                self._ctx_last_used.pop(k, None)
                if ctx is not None:
                    try:
                        ctx.close()
                    except Exception:
                        pass
                    self._evicted_contexts += 1

        # Hard cap eviction (oldest first)
        if max_ctx > 0 and len(self._contexts) > max_ctx:
            ordered = sorted(self._ctx_last_used.items(), key=lambda kv: kv[1])  # oldest first
            for k, _ts in ordered:
                if len(self._contexts) <= max_ctx:
                    break
                ctx = self._contexts.pop(k, None)
                self._ctx_last_used.pop(k, None)
                if ctx is not None:
                    try:
                        ctx.close()
                    except Exception:
                        pass
                    self._evicted_contexts += 1

        # Close browsers that no longer have contexts
        try:
            alive_proxy_keys = {proxy_key for (proxy_key, _src) in self._contexts.keys()}
            for proxy_key, br in list(self._browsers.items()):
                if proxy_key not in alive_proxy_keys:
                    try:
                        br.close()
                    except Exception:
                        pass
                    self._browsers.pop(proxy_key, None)
        except Exception:
            pass

    def fetch(
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
        time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

        ctx = self._get_or_create_context(proxy_server=proxy_server, source=source)

        page = ctx.new_page()
        # Context-level routing is preferred, but keep this as a safety net.
        try:
            self._block_heavy_resources(page, source=source)
        except Exception:
            pass
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)

            # Give JS challenges time to complete (Cloudflare/PerimeterX/DataDome patterns).
            # We re-check page content a few times before giving up.
            # This dramatically reduces false "blocked" when the challenge auto-solves.
            html = ""
            final_url = page.url
            for i in range(0, 10):
                page.wait_for_timeout(800 if i == 0 else 1200)
                html = page.content()
                final_url = page.url
                h = (html or "").lower()
                is_challenge = (
                    "captcha" in h
                    or "verify you are" in h
                    or "cloudflare" in h
                    or "incapsula" in h
                    or "datadome" in h
                    or "perimeterx" in h
                    or "access denied" in h
                    or "just a moment" in h
                )
                if not is_challenge:
                    break
            # done
        finally:
            try:
                page.close()
            except Exception:
                pass
            try:
                proxy_key = proxy_server or "__no_proxy__"
                storage_path = self._storage_path(proxy_key, (source or "unknown").lower().strip() or "unknown")
                ctx.storage_state(path=storage_path)
            except Exception:
                pass
        return PoolFetchResult(html=html, final_url=final_url)

    def fetch_json(
        self,
        url: str,
        *,
        source: str,
        proxy_server: Optional[str],
        timeout_ms: int,
        wait_until: str,
        capture_mode: str = "any_json",
        json_url_predicate: Optional[Callable[[str, dict, int], bool]] = None,
        min_delay_ms: int,
        max_delay_ms: int,
    ) -> PoolJsonFetchResult:
        time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

        ctx = self._get_or_create_context(proxy_server=proxy_server, source=source)

        captured_data: Optional[dict] = None
        captured_url: str = ""

        def _default_pred(url_: str, headers_: dict, status_: int) -> bool:
            ct = (headers_.get("content-type") or "").lower()
            return status_ == 200 and "application/json" in ct

        def _pred_from_capture_mode(mode: str) -> Callable[[str, dict, int], bool]:
            m = (mode or "any_json").strip().lower()
            if m in ("any_json", "json"):
                return _default_pred
            if m in ("next_data", "nextjs", "_next_data"):
                def _p(u: str, h: dict, s: int) -> bool:
                    ct = (h.get("content-type") or "").lower()
                    return s == 200 and ("application/json" in ct or u.endswith(".json")) and "/_next/data/" in u
                return _p
            if m.startswith("url_contains:"):
                needle = m.split(":", 1)[1]
                def _p(u: str, h: dict, s: int) -> bool:
                    if s != 200:
                        return False
                    ct = (h.get("content-type") or "").lower()
                    return needle in (u or "").lower() and ("application/json" in ct or u.endswith(".json"))
                return _p
            if m.startswith("url_regex:"):
                rx = m.split(":", 1)[1]
                try:
                    cre = re.compile(rx)
                except Exception:
                    cre = re.compile(re.escape(rx))
                def _p(u: str, h: dict, s: int) -> bool:
                    if s != 200:
                        return False
                    ct = (h.get("content-type") or "").lower()
                    return bool(cre.search(u or "")) and ("application/json" in ct or u.endswith(".json"))
                return _p
            # Unknown mode: fallback to any_json
            return _default_pred

        pred = json_url_predicate or _pred_from_capture_mode(capture_mode)

        page = ctx.new_page()
        self._block_heavy_resources(page, source=source)

        final_url = url
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
                storage_path = self._storage_path(proxy_key, (source or "unknown").lower().strip() or "unknown")
                ctx.storage_state(path=storage_path)
            except Exception:
                pass

        if not isinstance(captured_data, dict):
            raise RuntimeError("Browser JSON capture failed (no JSON response matched).")

        return PoolJsonFetchResult(data=captured_data, final_url=final_url, data_url=captured_url)


class _PlaywrightWorker(threading.Thread):
    """
    Dedicated thread that owns Playwright Sync objects.

    IMPORTANT: do NOT use attribute name '_started' here, it conflicts with threading.Thread internals.
    """

    def __init__(self) -> None:
        super().__init__(name="PlaywrightPoolWorker", daemon=True)
        self.q: "queue.Queue[_Job]" = queue.Queue()
        self._ready = threading.Event()
        self._boot_ok = False
        self._last_error: Optional[str] = None
        self._core = _PlaywrightCore()

    def run(self) -> None:
        # boot
        try:
            self._core.start()
            self._boot_ok = True
        except Exception:
            self._last_error = traceback.format_exc()
            self._boot_ok = False
        finally:
            self._ready.set()

        # main loop
        while True:
            job = self.q.get()
            if job.name == "__stop__":
                try:
                    self._core.close()
                finally:
                    job.done.set()
                break

            try:
                if job.name == "stats":
                    st = self._core.stats()
                    st["last_error"] = (self._last_error[:800] if self._last_error else None)
                    job.result = st
                elif job.name == "fetch":
                    job.result = self._core.fetch(**job.kwargs)
                elif job.name == "fetch_json":
                    job.result = self._core.fetch_json(**job.kwargs)
                else:
                    raise RuntimeError(f"Unknown Playwright job: {job.name}")
                job.exc = None
            except Exception as e:
                job.exc = e
                self._last_error = traceback.format_exc()
            finally:
                job.done.set()


class PlaywrightPool:
    """
    Thread-safe facade. All Playwright Sync calls run inside a dedicated worker thread.
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
            w._ready.wait(timeout=25)
            self._worker = w
            if not w._boot_ok:
                err = w._last_error or "Playwright worker failed to start."
                raise RuntimeError(err)

    def close(self) -> None:
        with self._lock:
            if not self._worker or not self._worker.is_alive():
                return
            job = _Job("__stop__", kwargs={}, done=threading.Event())
            self._worker.q.put(job)
        job.done.wait(timeout=15)
        with self._lock:
            try:
                self._worker.join(timeout=10)
            except Exception:
                pass
            self._worker = None


    def reset(self) -> None:
        """Hard reset for recovery (TargetClosed/ContextClosed).

        Stops the worker thread (closing all browsers/contexts) and starts a fresh one.
        Best-effort: never raises during the close phase.
        """
        try:
            self.close()
        except Exception:
            pass
        # Start will raise if Playwright isn't installed, which is the desired signal.
        self.start()

    def stats(self) -> dict:
        self.start()
        assert self._worker is not None
        job = _Job("stats", kwargs={}, done=threading.Event())
        self._worker.q.put(job)
        job.done.wait(timeout=5)
        if job.exc:
            raise job.exc
        return job.result

    def _call(self, name: str, *, hard_timeout_s: float, **kwargs):
        self.start()
        assert self._worker is not None
        job = _Job(name, kwargs=kwargs, done=threading.Event())
        self._worker.q.put(job)
        if not job.done.wait(timeout=hard_timeout_s):
            raise TimeoutError(f"Playwright worker timed out waiting for job '{name}'.")
        if job.exc:
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
        capture_mode: str = "any_json",
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
            capture_mode=capture_mode,
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
