from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import quote_plus, urlparse

from app.scrapers.scraper_base.fetcher import unified_fetch
from app.scrapers.shared.browser_manager import get_browser_manager
from app.services.source_dual_run_report import diagnose_mercadolivre_html
from app.sources.registry import get_source
from app.sources.types import ScrapeContext
from app.scrapers.sources.mercadolivre import MercadoLivreScraper


@dataclass
class ProbeStrategy:
    name: str
    url: str | None = None
    skip: bool = False
    skip_reason: str = ""
    kind: str = "auto"
    browser_wait_until: str | None = None
    browser_wait_scroll: bool = False


def _slugify_query(query: str) -> str:
    raw = (query or "").strip().lower()
    raw = re.sub(r"[^\w\s-]+", " ", raw, flags=re.UNICODE)
    slug = re.sub(r"[\s_]+", "-", raw).strip("-")
    return slug or "carro"


def _brand_model_url(query: str) -> str:
    slug = _slugify_query(query)
    model = slug.split("-")[0] if slug else ""
    brand_map = {"civic": "honda", "golf": "volkswagen", "corolla": "toyota"}
    brand = brand_map.get(model)
    if brand and model:
        return f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{brand}/{model}"
    return f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{slug}"


def build_strategies(query: str, include_browser: bool = False) -> list[ProbeStrategy]:
    slug = _slugify_query(query)
    plugin = get_source("mercadolivre")
    scraper = MercadoLivreScraper()

    strategies = [
        ProbeStrategy("html_listing_current", f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{slug}"),
        ProbeStrategy("lista_vehicle_brand_model", _brand_model_url(query)),
        ProbeStrategy("api_search_current", f"https://api.mercadolibre.com/sites/MLB/search?q={quote_plus(query)}&category=MLB1743"),
        ProbeStrategy("api_search_without_category", f"https://api.mercadolibre.com/sites/MLB/search?q={quote_plus(query)}"),
        ProbeStrategy("api_search_category_param_encoded", f"https://api.mercadolibre.com/sites/MLB/search?category=MLB1743&q={quote_plus(query)}"),
        ProbeStrategy("lista_query_param", f"https://lista.mercadolivre.com.br/{slug}"),
        ProbeStrategy("v2_build_search_url", scraper.build_search_url(query)),
    ]
    if plugin is not None:
        strategies.append(ProbeStrategy("plugin_build_url", plugin.build_url(query)))

    try:
        from curl_cffi import requests as creq  # type: ignore

        _ = creq
        strategies.append(ProbeStrategy("api_curl_cffi_chrome", f"https://api.mercadolibre.com/sites/MLB/search?q={quote_plus(query)}&category=MLB1743", kind="curl_cffi"))
    except Exception:
        strategies.append(ProbeStrategy("api_curl_cffi_chrome", skip=True, skip_reason="curl_cffi_not_installed", kind="curl_cffi"))

    if include_browser:
        strategies.extend(
            [
                ProbeStrategy("playwright_domcontentloaded", f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{slug}", kind="playwright", browser_wait_until="domcontentloaded"),
                ProbeStrategy("playwright_networkidle", f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{slug}", kind="playwright", browser_wait_until="networkidle"),
                ProbeStrategy("playwright_wait_scroll", f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{slug}", kind="playwright", browser_wait_until="domcontentloaded", browser_wait_scroll=True),
            ]
        )

    return strategies


def _json_diagnostics(content: str) -> dict[str, Any]:
    out: dict[str, Any] = {"json_detected": False, "json_results_count": 0}
    body = (content or "").strip()
    if not body.startswith("{") and not body.startswith("["):
        return out
    out["json_detected"] = True
    try:
        payload = json.loads(body)
    except Exception as exc:
        out["json_error"] = f"{type(exc).__name__}: {exc}"
        out["body_snippet"] = body[:300]
        return out
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            out["json_results_count"] = len(results)
        if payload.get("error") or payload.get("message"):
            out["json_error_message"] = str(payload.get("error") or payload.get("message"))
    return out


def _score_useful_data(row: dict[str, Any]) -> int:
    score = 0
    counts = row.get("selector_counts") or {}
    signals = set(row.get("signals") or [])
    if row.get("json_results_count", 0) > 0:
        score += 100
    if counts.get("li.ui-search-layout__item", 0) > 0:
        score += 80
    if counts.get("a_mlb_links", 0) > 0:
        score += 60
    if counts.get("a_vehicle_links", 0) > 0:
        score += 40
    if "has_preloaded_state" in signals or "has_json_ld" in signals:
        score += 20
    if row.get("fetch_blocked") or (signals & {"bot_challenge", "access_denied", "captcha"}):
        score -= 100
    if row.get("content_length", 0) > 3000 and counts.get("a_mlb_links", 0) == 0 and counts.get("li.ui-search-layout__item", 0) == 0:
        score -= 30
    return score


def _fetch_with_playwright(strategy: ProbeStrategy, source: str) -> dict[str, Any]:
    try:
        browser_mgr = get_browser_manager()
    except Exception:
        return {"skipped": True, "reason": "playwright_unavailable"}
    start = perf_counter()
    try:
        if strategy.browser_wait_scroll:
            result = browser_mgr.fetch_html_with_actions(
                url=strategy.url,
                source=source,
                proxy=None,
                timeout_ms=30000,
                wait_until="domcontentloaded",
                block_resources=False,
                extra_wait_ms=3000,
                scroll=True,
            )
        else:
            result = browser_mgr.fetch_html(url=strategy.url, source=source, proxy=None, timeout_ms=30000, wait_until=strategy.browser_wait_until or "domcontentloaded", block_resources=False)
        content = result.html or ""
        return {
            "fetch_ok": True,
            "fetch_blocked": False,
            "fetch_method": f"playwright:{strategy.browser_wait_until}",
            "duration_ms": int((perf_counter() - start) * 1000),
            "final_url": getattr(result, "final_url", strategy.url),
            "content": content,
        }
    except Exception as exc:
        return {
            "fetch_ok": False,
            "fetch_blocked": "403" in str(exc),
            "error": f"{type(exc).__name__}: {exc}",
            "fetch_method": f"playwright:{strategy.browser_wait_until}",
            "duration_ms": int((perf_counter() - start) * 1000),
            "final_url": strategy.url,
            "content": "",
        }


def run_probe(query: str, capture_dir: str | None = None, include_browser: bool = False) -> dict[str, Any]:
    ctx = ScrapeContext(source="mercadolivre", force_browser=False, browser_fallback_enabled=True, extra={})
    strategies = build_strategies(query, include_browser=include_browser)
    results: list[dict[str, Any]] = []
    capture_base = Path(capture_dir) if capture_dir else None
    if capture_base:
        capture_base.mkdir(parents=True, exist_ok=True)

    for strategy in strategies:
        row: dict[str, Any] = {"strategy_name": strategy.name, "url": strategy.url or "", "skipped": strategy.skip}
        if strategy.skip:
            row["reason"] = strategy.skip_reason
            results.append(row)
            continue

        if strategy.kind == "playwright":
            prow = _fetch_with_playwright(strategy, "mercadolivre")
            if prow.get("skipped"):
                row.update(prow)
                results.append(row)
                continue
            content = prow.pop("content", "")
            row.update(prow)
        else:
            start = perf_counter()
            try:
                if strategy.kind == "curl_cffi":
                    from curl_cffi import requests as creq  # type: ignore

                    response = creq.get(strategy.url, timeout=20, impersonate="chrome120", allow_redirects=True)
                    content = response.text or ""
                    row.update({"fetch_ok": True, "fetch_blocked": int(response.status_code) in (403, 429), "http_status": int(response.status_code), "fetch_method": "curl_cffi", "content_type": response.headers.get("content-type", "")})
                else:
                    fetched = unified_fetch(strategy.url, ctx, source="mercadolivre")
                    content = fetched.content or ""
                    row.update({"fetch_ok": True, "fetch_blocked": False, "fetch_method": getattr(fetched, "method", ""), "duration_ms": getattr(fetched, "duration_ms", None), "final_url": getattr(fetched, "final_url", strategy.url)})
            except Exception as exc:
                content = ""
                msg = f"{type(exc).__name__}: {exc}"
                row.update({"fetch_ok": False, "fetch_blocked": ("403" in msg or "FetchBlocked" in msg), "error": msg, "final_url": strategy.url})
            row.setdefault("duration_ms", int((perf_counter() - start) * 1000))

        row["content_length"] = len(content)
        json_diag = _json_diagnostics(content)
        row.update(json_diag)
        if not row.get("json_detected"):
            html_diag = diagnose_mercadolivre_html(content)
            row.update({"title": html_diag.get("title", ""), "canonical_url": html_diag.get("canonical_url", ""), "og_url": html_diag.get("og_url", ""), "selector_counts": html_diag.get("selector_counts", {}), "signals": html_diag.get("signals", []), "sample_links": html_diag.get("sample_links", [])})
        row["useful_data_score"] = _score_useful_data(row)

        if capture_base and content:
            suffix = "json" if row.get("json_detected") else "html"
            safe_name = re.sub(r"[^a-z0-9_\-]", "_", strategy.name.lower())
            target = capture_base / f"mercadolivre_{safe_name}.{suffix}"
            target.write_text(content, encoding="utf-8")
            row["capture_path"] = str(target)
        results.append(row)

    recommended_row = max(results, key=lambda x: x.get("useful_data_score", -9999), default={}) if results else {}
    recommended = recommended_row.get("strategy_name", "") if recommended_row.get("useful_data_score", 0) > 0 else ""

    if recommended:
        status = "OK"
    else:
        non_skipped = [r for r in results if not r.get("skipped")]
        if non_skipped and all(r.get("fetch_blocked") or r.get("fetch_ok") is False for r in non_skipped):
            status = "FAIL"
        elif non_skipped and all(r.get("fetch_ok") for r in non_skipped):
            status = "INCONCLUSIVE"
        elif any(r.get("fetch_ok") for r in non_skipped):
            status = "WARN"
        else:
            status = "FAIL"

    return {"source": "mercadolivre", "query": query, "summary_status": status, "recommended_strategy": recommended, "strategies": results}
