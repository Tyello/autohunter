from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass

from app.scrapers.base import FetchBlocked
from app.core.settings import settings


@dataclass
class BrowserFetchResult:
    html: str
    final_url: str


def _looks_like_bot_challenge(html: str) -> bool:
    h = html.lower()
    return (
        "captcha" in h
        or "verify you are" in h
        or "cloudflare" in h
        or "incapsula" in h
        or "datadome" in h
        or "perimeterx" in h
        or "access denied" in h
    )


def fetch_html_browser(
    url: str,
    *,
    timeout_ms: int = 30000,
    wait_until: str = "networkidle",
    min_delay_ms: int = 250,
    max_delay_ms: int = 900,
) -> BrowserFetchResult:
    """Render a page in a real browser (Playwright) and return the resulting HTML.

    This is the escape hatch for SPA/JS-heavy sources (Webmotors/GoGarage) and
    for sources that frequently block simple HTTP clients (OLX).

    Requirements:
    - pip install playwright
    - playwright install chromium

    Env:
    - PLAYWRIGHT_HEADLESS=true|false (default true)
    """

    # small random delay to reduce patterns
    time.sleep(random.randint(min_delay_ms, max_delay_ms) / 1000.0)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Playwright not installed. Run: pip install playwright && playwright install chromium"
        ) from e

    headless_env = os.getenv("PLAYWRIGHT_HEADLESS")
    if headless_env is None:
        headless = bool(settings.playwright_headless)
    else:
        headless = headless_env.lower() not in ("0", "false", "no")

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ]
    ua = random.choice(user_agents)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=ua,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": random.choice([1280, 1366, 1440]), "height": random.choice([720, 800, 900])},
        )

        # Block heavy resources
        def _route(route):
            rtype = route.request.resource_type
            if rtype in ("image", "media", "font"):
                return route.abort()
            return route.continue_()

        page = context.new_page()
        page.route("**/*", _route)

        try:
            page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            # quick extra wait for late hydration
            page.wait_for_timeout(500)
            html = page.content()
            final_url = page.url
        finally:
            context.close()
            browser.close()

    if _looks_like_bot_challenge(html):
        raise FetchBlocked(200, url, reason="bot_challenge")

    return BrowserFetchResult(html=html, final_url=final_url)
