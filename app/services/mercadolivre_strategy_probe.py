from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import quote_plus, urlparse

from app.scrapers.scraper_base.fetcher import unified_fetch
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


def _slugify_query(query: str) -> str:
    raw = (query or "").strip().lower()
    raw = re.sub(r"[^\w\s-]+", " ", raw, flags=re.UNICODE)
    slug = re.sub(r"[\s_]+", "-", raw).strip("-")
    return slug or "carro"


def build_strategies(query: str) -> list[ProbeStrategy]:
    slug = _slugify_query(query)
    plugin = get_source("mercadolivre")
    scraper = MercadoLivreScraper()

    strategies = [
        ProbeStrategy("html_listing_current", f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{slug}"),
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
            if results and isinstance(results[0], dict):
                out["sample_result_keys"] = sorted(list(results[0].keys()))[:10]
                hosts: list[str] = []
                for item in results[:5]:
                    link = (item or {}).get("permalink") or (item or {}).get("url")
                    host = urlparse(link).netloc if isinstance(link, str) else ""
                    if host:
                        hosts.append(host)
                out["sample_permalink_hosts"] = sorted(set(hosts))
        if payload.get("error") or payload.get("message"):
            out["json_error_message"] = str(payload.get("error") or payload.get("message"))
    return out


def _recommend_next(item: dict[str, Any]) -> str:
    if item.get("skipped"):
        return "install_optional_dependency_or_skip"
    if item.get("fetch_blocked"):
        return "blocked_403_or_challenge_try_alternative_fetch"
    if item.get("json_results_count", 0) > 0:
        return "json_results_available"
    counts = (item.get("selector_counts") or {})
    if counts.get("a_mlb_links", 0) > 0 or counts.get("li.ui-search-layout__item", 0) > 0:
        return "html_links_available"
    if item.get("fetch_ok"):
        return "fetch_ok_but_shell_or_no_results"
    return "fetch_error_investigate"


def run_probe(query: str, capture_dir: str | None = None) -> dict[str, Any]:
    ctx = ScrapeContext(source="mercadolivre", force_browser=False, browser_fallback_enabled=True, extra={})
    strategies = build_strategies(query)
    results: list[dict[str, Any]] = []
    capture_base = Path(capture_dir) if capture_dir else None
    if capture_base:
        capture_base.mkdir(parents=True, exist_ok=True)

    for strategy in strategies:
        row: dict[str, Any] = {"strategy_name": strategy.name, "url": strategy.url or "", "skipped": strategy.skip}
        if strategy.skip:
            row["reason"] = strategy.skip_reason
            row["recommended_next_step"] = _recommend_next(row)
            results.append(row)
            continue

        start = perf_counter()
        try:
            if strategy.kind == "curl_cffi":
                from curl_cffi import requests as creq  # type: ignore

                response = creq.get(strategy.url, timeout=20, impersonate="chrome120", allow_redirects=True)
                content = response.text or ""
                row.update({
                    "fetch_ok": True,
                    "fetch_blocked": int(response.status_code) in (403, 429),
                    "http_status": int(response.status_code),
                    "fetch_method": "curl_cffi",
                    "content_type": response.headers.get("content-type", ""),
                })
            else:
                fetched = unified_fetch(strategy.url, ctx, source="mercadolivre")
                content = fetched.content or ""
                row.update({
                    "fetch_ok": True,
                    "fetch_blocked": False,
                    "fetch_method": getattr(fetched, "method", ""),
                    "duration_ms": getattr(fetched, "duration_ms", None),
                })
        except Exception as exc:
            content = ""
            msg = f"{type(exc).__name__}: {exc}"
            blocked = "403" in msg or "FetchBlocked" in msg
            row.update({"fetch_ok": False, "fetch_blocked": blocked, "error": msg})

        row.setdefault("duration_ms", int((perf_counter() - start) * 1000))
        row["content_length"] = len(content)

        json_diag = _json_diagnostics(content)
        row.update(json_diag)

        if not row.get("json_detected"):
            html_diag = diagnose_mercadolivre_html(content)
            row.update(
                {
                    "title": html_diag.get("title", ""),
                    "canonical_url": html_diag.get("canonical_url", ""),
                    "og_url": html_diag.get("og_url", ""),
                    "selector_counts": html_diag.get("selector_counts", {}),
                    "signals": html_diag.get("signals", []),
                    "sample_links": html_diag.get("sample_links", []),
                }
            )
        row["recommended_next_step"] = _recommend_next(row)

        if capture_base and content:
            suffix = "json" if row.get("json_detected") else "html"
            safe_name = re.sub(r"[^a-z0-9_\-]", "_", strategy.name.lower())
            target = capture_base / f"mercadolivre_{safe_name}.{suffix}"
            target.write_text(content, encoding="utf-8")
            row["capture_path"] = str(target)

        results.append(row)

    useful = [
        r
        for r in results
        if (r.get("json_results_count", 0) > 0)
        or ((r.get("selector_counts") or {}).get("a_mlb_links", 0) > 0)
        or ((r.get("selector_counts") or {}).get("li.ui-search-layout__item", 0) > 0)
    ]
    fetch_ok = [r for r in results if r.get("fetch_ok")]
    blocked_or_err = [r for r in results if r.get("fetch_blocked") or (r.get("fetch_ok") is False and not r.get("skipped"))]

    if useful:
        status = "OK"
        recommended = useful[0].get("strategy_name", "")
    elif fetch_ok and len(fetch_ok) == len([r for r in results if not r.get("skipped")]):
        status = "INCONCLUSIVE"
        recommended = ""
    elif blocked_or_err and len(blocked_or_err) == len([r for r in results if not r.get("skipped")]):
        status = "FAIL"
        recommended = ""
    elif fetch_ok:
        status = "WARN"
        recommended = ""
    else:
        status = "FAIL"
        recommended = ""

    return {"source": "mercadolivre", "query": query, "summary_status": status, "recommended_strategy": recommended, "strategies": results}
