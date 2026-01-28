from __future__ import annotations

import re
from urllib.parse import urljoin

from app.services.browser_fetcher import fetch_html_browser
from app.sources.types import ScrapeContext


def _extract_ids(html_text: str) -> set[str]:
    ids: set[str] = set()
    for m in re.finditer(r"/marketplace/item/(\d+)", html_text):
        ids.add(m.group(1))
    return ids


def scrape_facebook_marketplace(search_url: str, ctx: ScrapeContext) -> list[dict]:
    """Facebook Marketplace scraper (Playwright-only).

    Notes:
    - Marketplace is highly dynamic and may require an authenticated session.
    - This scraper extracts item URLs best-effort (title/price are often behind dynamic components).
    - To improve results, run Playwright with a persistent storage_state (already supported by the pool)
      and login once manually (headless=false), then re-enable headless.
    """
    res = fetch_html_browser(search_url, ctx=ctx, timeout_ms=60000, wait_until="networkidle")
    html_text = res.html
    final_url = res.final_url or search_url

    ids = _extract_ids(html_text)
    out: list[dict] = []
    for item_id in sorted(ids)[:120]:
        url = urljoin(final_url, f"/marketplace/item/{item_id}/")
        out.append({
            "source": "facebook_marketplace",
            "external_id": item_id,
            "url": url,
            "title": None,
            "price": None,
            "thumbnail_url": None,
            "location": None,
        })

    # If no ids were found, try alternate URL patterns
    if not out:
        for m in re.finditer(r"https?://www\.facebook\.com/marketplace/item/(\d+)", html_text):
            item_id = m.group(1)
            url = m.group(0)
            out.append({
                "source": "facebook_marketplace",
                "external_id": item_id,
                "url": url,
                "title": None,
                "price": None,
                "thumbnail_url": None,
                "location": None,
            })

    return out
