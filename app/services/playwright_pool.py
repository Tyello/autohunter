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

from app.core.runtime_paths import playwright_browsers_dir, playwright_storage_dir
from app.core.settings import settings, ensure_playwright_browsers_env
from app.scrapers.base import FetchBlocked
from app.scrapers.webmotors_ops import detect_webmotors_challenge


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
        base = playwright_storage_dir()
        base.mkdir(parents=True, exist_ok=True)
        safe_proxy = proxy_key.replace(":", "_").replace("/", "_")
        safe_source = source.replace(":", "_").replace("/", "_")
        return str(base / f"storage_{safe_source}__{safe_proxy}.json")

    def _block_heavy_resources(self, page: Any, *, source: str, block_resources: bool = True) -> None:
        """Block heavy resources to reduce RAM/CPU on small machines.

        IMPORTANT: Some anti-bot challenges rely on fetching images or other
        resources. For a small allowlist of "hostile" sources we do NOT block.
        """
        if not block_resources:
            return

        src = (source or "").strip().lower()
        allow_heavy = src in {"mobiauto", "icarros", "facebook_marketplace"}
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
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-breakpad",
                "--disable-client-side-phishing-detection",
                "--disable-component-update",
                "--disable-default-apps",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-hang-monitor",
                "--disable-ipc-flooding-protection",
                "--disable-popup-blocking",
                "--disable-prompt-on-repost",
                "--disable-renderer-backgrounding",
                "--disable-sync",
                "--disable-translate",
                "--metrics-recording-only",
                "--mute-audio",
                "--no-default-browser-check",
                "--no-first-run",
                "--no-service-autorun",
                "--password-store=basic",
            ],
            # Remove the automation flag when possible
            "ignore_default_args": ["--enable-automation"],
        }
        if proxy_server:
            launch_kwargs["proxy"] = {"server": proxy_server}

        browsers_path = playwright_browsers_dir()
        browsers_path.mkdir(parents=True, exist_ok=True)
        ensure_playwright_browsers_env()

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
                        # fallback to configured runtime cache
                        ms_dir = playwright_browsers_dir() / "ms-playwright"

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

        headless = bool(settings.playwright_headless)

        b = self._launch_browser(proxy_server=proxy_server, headless=headless)
        self._browsers[key] = b
        return b

    def warmup(
        self,
        *,
        source: str,
        proxy_server: Optional[str],
        url: Optional[str] = None,
        timeout_ms: int = 120000,
        wait_until: str = "domcontentloaded",
        behavior: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Warm up cookies/storage_state for a given source/domain.

        This is mainly used for sources that present anti-bot challenges with HTTP 200.
        We intentionally avoid wait_until='networkidle' which can hang forever on ad-heavy pages.
        """
        src = (source or "unknown").lower().strip() or "unknown"
        proxy_key = proxy_server or "__no_proxy__"
        storage_path = self._storage_path(proxy_key, src)

        browser = self._get_or_create_browser(proxy_server)

        # Use the same fingerprint logic as _get_or_create_context
        if src == "webmotors":
            ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            viewport = {"width": 1366, "height": 768}
        else:
            ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            viewport = {"width": 1366, "height": 768}

        ctx = browser.new_context(
            user_agent=ua,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport=viewport,
        )

        try:
            started = time.time()
            page = ctx.new_page()
            steps_completed: list[str] = []
            behavior_cfg = behavior or {}
            # do not block heavy resources for warmup; challenges often rely on them
            target_url = (url or "").strip()
            if not target_url and src == "webmotors":
                target_url = "https://www.webmotors.com.br/"
            if target_url:
                page.goto(target_url, wait_until=wait_until, timeout=timeout_ms)
                page.wait_for_timeout(1500)
                steps_completed.append("home")
                if src == "webmotors" and "webmotors.com.br" in target_url:
                    page.goto(
                        "https://www.webmotors.com.br/carros",
                        wait_until=wait_until,
                        timeout=timeout_ms,
                    )
                    page.wait_for_timeout(2000)
                    steps_completed.append("cars_page")
            def _behavior_bool(cfg: Dict[str, Any], key: str, default: bool) -> bool:
                value = cfg.get(key)
                if value is None:
                    return default
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    normalized = value.strip().lower()
                    if normalized in {"1", "true", "yes", "on", "sim"}:
                        return True
                    if normalized in {"0", "false", "no", "off", "nao", "não"}:
                        return False
                return bool(value)

            def _behavior_int(cfg: Dict[str, Any], key: str, default: int) -> int:
                value = cfg.get(key)
                if value is None:
                    return default
                try:
                    return int(value)
                except Exception:
                    return default

            if src == "webmotors" and _behavior_bool(behavior_cfg, "webmotors_warmup_behavior_enabled", False):
                if _behavior_bool(behavior_cfg, "webmotors_warmup_scroll_enabled", True):
                    try:
                        page.evaluate("window.scrollTo({top: 300, behavior: 'smooth'})")
                        page.wait_for_timeout(250)
                        page.evaluate("window.scrollTo({top: 700, behavior: 'smooth'})")
                        page.wait_for_timeout(250)
                        page.evaluate("window.scrollTo({top: 450, behavior: 'smooth'})")
                        steps_completed.append("scroll")
                    except Exception:
                        steps_completed.append("scroll_failed")
                if _behavior_bool(behavior_cfg, "webmotors_warmup_mouse_enabled", True):
                    try:
                        page.mouse.move(120, 140)
                        page.wait_for_timeout(120)
                        page.mouse.move(280, 220)
                        page.wait_for_timeout(120)
                        page.mouse.move(460, 320)
                        steps_completed.append("mouse")
                    except Exception:
                        steps_completed.append("mouse_failed")
                if _behavior_bool(behavior_cfg, "webmotors_warmup_consent_enabled", True):
                    try:
                        clicked = False
                        for t in ("aceitar", "concordo", "entendi", "permitir", "ok"):
                            for selector in (
                                f"button:has-text('{t}')",
                                f"a:has-text('{t}')",
                                f"input[type='button'][value*='{t}' i]",
                                f"input[type='submit'][value*='{t}' i]",
                            ):
                                el = page.query_selector(selector)
                                if el:
                                    el.click(timeout=1500)
                                    page.wait_for_timeout(600)
                                    clicked = True
                        if clicked:
                            steps_completed.append("consent_clicked")
                        else:
                            steps_completed.append("consent_attempted")
                    except Exception:
                        steps_completed.append("consent_failed")
                extra_wait_ms = _behavior_int(behavior_cfg, "webmotors_warmup_extra_wait_ms", 1500)
                extra_wait_ms = max(0, min(extra_wait_ms, 5000))
                if extra_wait_ms:
                    page.wait_for_timeout(extra_wait_ms)
                    steps_completed.append("extra_wait")

            html = ""
            try:
                html = page.content()
            except Exception:
                html = ""
            title = ""
            try:
                title = page.title()
            except Exception:
                title = ""

            # Save state even if the page is not perfect; but report if it still looks like a challenge
            Path(storage_path).parent.mkdir(parents=True, exist_ok=True)
            ctx.storage_state(path=storage_path)
            steps_completed.append("storage_state")

            # Invalidate cached context for this (proxy,source) so next fetch reloads storage_state
            try:
                keys_to_drop = [k for k in self._contexts.keys() if len(k) == 3 and k[0] == proxy_key and k[1] == src]
                for k in keys_to_drop:
                    old = self._contexts.pop(k, None)
                    self._ctx_last_used.pop(k, None)
                    if old is not None:
                        try:
                            old.close()
                        except Exception:
                            pass
            except Exception:
                pass

            final_url = getattr(page, "url", "") or ""
            challenge = detect_webmotors_challenge(html=html, title=title, final_url=final_url)
            return {
                "ok": True,
                "source": src,
                "storage_path": storage_path,
                "still_challenge": bool(challenge.get("still_challenge")),
                "challenge_provider": challenge.get("provider"),
                "challenge_reason": challenge.get("reason"),
                "challenge_signals": challenge.get("signals") or [],
                "final_url": final_url,
                "title": title,
                "steps_completed": steps_completed,
                "duration_ms": int((time.time() - started) * 1000),
                "storage_state_saved": True,
            }
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    def _get_or_create_context(self, *, proxy_server: Optional[str], source: str, block_resources: bool = True) -> Any:
        # keep memory stable
        self._cleanup_contexts()
        src = (source or "unknown").lower().strip() or "unknown"
        proxy_key = proxy_server or "__no_proxy__"
        key = (proxy_key, src, bool(block_resources))
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
        # Use a stable fingerprint for sensitive sources (e.g., webmotors) to avoid
        # cookie/UA mismatch across runs.
        if src == "webmotors":
            ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            viewport = {"width": 1366, "height": 768}
        else:
            ua = random.choice(user_agents)
            viewport = {"width": random.choice([1280, 1366, 1440]), "height": random.choice([720, 800, 900])}

        storage_path = self._storage_path(proxy_key, src)
        storage_state = storage_path if os.path.exists(storage_path) else None

        ctx = browser.new_context(
            user_agent=ua,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport=viewport,
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
            heavy_ok_sources = {"mobiauto", "icarros", "facebook_marketplace"}
            should_block = bool(block_resources)
            if src in heavy_ok_sources and bool(block_resources):
                should_block = False
            if should_block:
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
            alive_proxy_keys = {proxy_key for (proxy_key, _src, _blk) in self._contexts.keys()}
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
        block_resources: bool = True,
    ) -> PoolFetchResult:
        time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

        ctx = self._get_or_create_context(proxy_server=proxy_server, source=source, block_resources=block_resources)

        page = ctx.new_page()
        # Context-level routing is preferred, but keep this as a safety net.
        try:
            self._block_heavy_resources(page, source=source, block_resources=block_resources)
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
        block_resources: bool = True,
    ) -> PoolJsonFetchResult:
        time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

        ctx = self._get_or_create_context(proxy_server=proxy_server, source=source, block_resources=block_resources)

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
                    # capture even when blocked (403/429) to fail fast with a clear reason
                    if s not in (200, 403, 429):
                        return False
                    return "/_next/data/" in (u or "")
                return _p
            if m.startswith("url_contains:"):
                needle = m.split(":", 1)[1].lower()
                def _p(u: str, h: dict, s: int) -> bool:
                    if s not in (200, 403, 429):
                        return False
                    return needle in (u or "").lower()
                return _p
            if m.startswith("url_regex:"):
                rx = m.split(":", 1)[1]
                try:
                    cre = re.compile(rx)
                except Exception:
                    cre = re.compile(re.escape(rx))
                def _p(u: str, h: dict, s: int) -> bool:
                    if s not in (200, 403, 429):
                        return False
                    return bool(cre.search(u or ""))
                return _p
            # Unknown mode: fallback to any_json
            return _default_pred

        pred = json_url_predicate or _pred_from_capture_mode(capture_mode)

        page = ctx.new_page()
        self._block_heavy_resources(page, source=source, block_resources=block_resources)

        final_url = url
        try:
            captured_resp: dict[str, object] = {"resp": None}

            def _on_response(resp: Any) -> None:
                try:
                    if captured_resp["resp"] is None and pred(resp.url, resp.headers, resp.status):
                        captured_resp["resp"] = resp
                except Exception:
                    pass

            try:
                page.on("response", _on_response)
            except Exception:
                pass

            page.goto(url, wait_until=wait_until, timeout=timeout_ms)

            deadline = time.time() + (timeout_ms / 1000.0)
            while time.time() < deadline and captured_resp["resp"] is None:
                page.wait_for_timeout(150)

            resp = captured_resp["resp"]
            if resp is None:
                raise TimeoutError(f"No JSON response matched (capture_mode={capture_mode})")

            captured_url = resp.url
            final_url = page.url

            status = int(getattr(resp, "status", 0) or 0)
            if status in (403, 429):
                raise FetchBlocked(status, captured_url, reason="http_status")

            try:
                captured_data = resp.json()
            except Exception:
                # Some sources return HTML challenges behind a 200; treat as blocked.
                raise FetchBlocked(status or 200, captured_url, reason="non_json")
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
                elif job.name == "warmup":
                    job.result = self._core.warmup(**job.kwargs)
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
        block_resources: bool = True,
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
            block_resources=block_resources,
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
        block_resources: bool = True,
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
            block_resources=block_resources,
        )

    def warmup(
        self,
        url: Optional[str] = None,
        *,
        source: str,
        proxy_server: Optional[str] = None,
        timeout_ms: int = 120000,
        wait_until: str = "domcontentloaded",
        behavior: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Warm up cookies/storage_state for a given source (best-effort)."""
        self.start()
        assert self._worker is not None
        hard_timeout_s = max(15.0, (timeout_ms / 1000.0) + 30.0)
        return self._call(
            "warmup",
            hard_timeout_s=hard_timeout_s,
            url=url,
            source=source,
            proxy_server=proxy_server,
            timeout_ms=timeout_ms,
            wait_until=wait_until,
            behavior=behavior,
        )



_POOL: Optional[PlaywrightPool] = None


def get_playwright_pool() -> PlaywrightPool:
    global _POOL
    if _POOL is None:
        _POOL = PlaywrightPool()
    return _POOL
