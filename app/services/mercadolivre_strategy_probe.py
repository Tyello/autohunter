from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import quote_plus

from app.scrapers.scraper_base.fetcher import unified_fetch
from app.scrapers.shared.browser_manager import get_browser_manager
from app.scrapers.sources.mercadolivre import MercadoLivreScraper
from app.services.source_dual_run_report import diagnose_mercadolivre_html
from app.sources.registry import get_source
from app.sources.types import ScrapeContext


@dataclass
class ProbeFetchStrategy:
    name: str
    kind: str  # http|curl_cffi|playwright
    wait_until: str | None = None
    wait_scroll: bool = False
    skipped: bool = False
    reason: str = ""


def _slugify_query(query: str) -> str:
    text = re.sub(r"[^\w\s-]+", " ", (query or "").strip().lower(), flags=re.UNICODE)
    slug = re.sub(r"[\s_]+", "-", text).strip("-")
    return slug or "carro"


def _infer_brand_model_path(query: str) -> str | None:
    model = _slugify_query(query).split("-")[0]
    brand = {"civic": "honda", "golf": "volkswagen", "corolla": "toyota"}.get(model)
    if not brand:
        return None
    return f"{brand}/{model}"


def build_mercadolivre_strategy_urls(query: str, external_id: str | None = None) -> list[dict[str, str]]:
    slug = _slugify_query(query)
    plugin = get_source("mercadolivre")
    scraper = MercadoLivreScraper()
    rows: list[dict[str, str]] = []
    if plugin:
        rows.append({"strategy": "plugin_build_url", "url": plugin.build_url(query), "kind": "html", "source": "plugin"})
    rows.extend(
        [
            {"strategy": "v2_build_search_url", "url": scraper.build_search_url(query), "kind": "api", "source": "v2"},
            {"strategy": "lista_generic_slug", "url": f"https://lista.mercadolivre.com.br/{slug}", "kind": "html", "source": "manual"},
            {"strategy": "lista_vehicle_slug", "url": f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{slug}", "kind": "html", "source": "manual"},
            {"strategy": "api_with_category", "url": f"https://api.mercadolibre.com/sites/MLB/search?q={quote_plus(query)}&category=MLB1743", "kind": "api", "source": "manual"},
            {"strategy": "api_without_category", "url": f"https://api.mercadolibre.com/sites/MLB/search?q={quote_plus(query)}", "kind": "api", "source": "manual"},
            {"strategy": "api_category_first", "url": f"https://api.mercadolibre.com/sites/MLB/search?category=MLB1743&q={quote_plus(query)}", "kind": "api", "source": "manual"},
        ]
    )
    brand_model = _infer_brand_model_path(query)
    if brand_model:
        rows.append({"strategy": "lista_vehicle_brand_model", "url": f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{brand_model}", "kind": "derived", "source": "derived"})
    if external_id:
        norm = external_id.replace("MLB", "").replace("-", "").strip()
        if norm:
            rows.append({"strategy": "vip_from_external_id", "url": f"https://carro.mercadolivre.com.br/MLB-{norm}-_JM", "kind": "vip", "source": "derived"})
    return rows


def _build_fetch_strategies(include_browser: bool) -> list[ProbeFetchStrategy]:
    out = [ProbeFetchStrategy("unified_fetch", "http")]
    try:
        from curl_cffi import requests as _  # type: ignore
        out.append(ProbeFetchStrategy("curl_cffi_direct", "curl_cffi"))
    except Exception:
        out.append(ProbeFetchStrategy("curl_cffi_direct", "curl_cffi", skipped=True, reason="curl_cffi_not_installed"))
    if include_browser:
        out.extend([
            ProbeFetchStrategy("playwright_domcontentloaded", "playwright", wait_until="domcontentloaded"),
            ProbeFetchStrategy("playwright_networkidle", "playwright", wait_until="networkidle"),
            ProbeFetchStrategy("playwright_wait_scroll", "playwright", wait_until="domcontentloaded", wait_scroll=True),
        ])
    return out


def _json_diagnostics(content: str) -> dict[str, Any]:
    out: dict[str, Any] = {"json_detected": False, "json_results_count": None, "json_error_message": ""}
    body = (content or "").strip()
    if not body.startswith(("{", "[")):
        return out
    out["json_detected"] = True
    try:
        payload = json.loads(body)
    except Exception as exc:
        out["json_error_message"] = f"{type(exc).__name__}: {exc}"
        return out
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            out["json_results_count"] = len(results)
        if payload.get("error"):
            out["json_error_message"] = str(payload.get("error"))
    return out


def _compute_useful_data_score(row: dict[str, Any]) -> int:
    score = 0
    counts = row.get("html_diagnostics", {}).get("selector_counts", {})
    signals = set(row.get("html_diagnostics", {}).get("signals", []))
    if (row.get("json_results_count") or 0) > 0:
        score += 100
    if counts.get("li.ui-search-layout__item", 0) > 0:
        score += 80
    if counts.get("a_mlb_links", 0) > 0:
        score += 60
    if counts.get("a_vehicle_links", 0) > 0:
        score += 40
    if "has_preloaded_state" in signals or "has_json_ld" in signals:
        score += 20
    if row.get("fetch_blocked") or signals.intersection({"bot_challenge", "access_denied", "captcha"}):
        score -= 100
    if row.get("content_length", 0) > 3000 and counts.get("li.ui-search-layout__item", 0) == 0 and counts.get("a_mlb_links", 0) == 0:
        score -= 30
    return score


def _fetch_playwright(url: str, strategy: ProbeFetchStrategy, timeout_ms: int) -> dict[str, Any]:
    bm = get_browser_manager()
    if strategy.wait_scroll:
        result = bm.fetch_html_with_actions(url=url, source="mercadolivre", proxy=None, timeout_ms=timeout_ms, wait_until="domcontentloaded", block_resources=False, extra_wait_ms=3000, scroll=True)
    else:
        result = bm.fetch_html(url=url, source="mercadolivre", proxy=None, timeout_ms=timeout_ms, wait_until=strategy.wait_until or "domcontentloaded", block_resources=False)
    return {"content": result.html or "", "final_url": getattr(result, "final_url", url), "http_status": None, "content_type": "text/html"}


def run_probe(query: str, capture_dir: str | None = None, include_browser: bool = False, external_id: str | None = None, timeout_ms: int = 30000, limit_strategies: int | None = None) -> dict[str, Any]:
    urls = build_mercadolivre_strategy_urls(query, external_id=external_id)
    if limit_strategies is not None:
        urls = urls[: max(limit_strategies, 0)]
    fetchers = _build_fetch_strategies(include_browser)
    ctx = ScrapeContext(source="mercadolivre", force_browser=False, browser_fallback_enabled=True, extra={})
    capture_base = Path(capture_dir) if capture_dir else None
    if capture_base:
        capture_base.mkdir(parents=True, exist_ok=True)

    attempts: list[dict[str, Any]] = []
    for u in urls:
        for f in fetchers:
            row = {"url_strategy": u["strategy"], "fetch_strategy": f.name, "url": u["url"], "fetch_ok": False, "fetch_blocked": False, "http_status": None, "error": "", "fetch_method": "", "duration_ms": 0, "final_url": "", "content_type": "", "content_length": 0, "json_detected": False, "json_results_count": None, "json_error_message": "", "html_diagnostics": {"title": "", "canonical_url": "", "og_url": "", "selector_counts": {}, "signals": [], "sample_links": []}, "useful_data_score": 0, "recommended": False}
            if f.skipped:
                row["error"] = f.reason
                attempts.append(row)
                continue
            start = perf_counter()
            content = ""
            try:
                if f.kind == "http":
                    got = unified_fetch(u["url"], ctx, source="mercadolivre")
                    content = got.content or ""
                    row.update({"fetch_ok": True, "fetch_method": getattr(got, "method", "unified_fetch"), "final_url": getattr(got, "final_url", u["url"])})
                elif f.kind == "curl_cffi":
                    from curl_cffi import requests as creq  # type: ignore
                    resp = creq.get(u["url"], timeout=max(5, timeout_ms // 1000), impersonate="chrome", allow_redirects=True, headers={"accept-language": "pt-BR,pt;q=0.9"})
                    content = resp.text or ""
                    row.update({"fetch_ok": True, "http_status": int(resp.status_code), "fetch_blocked": int(resp.status_code) in (403, 429), "fetch_method": "curl_cffi_direct", "content_type": resp.headers.get("content-type", ""), "final_url": str(resp.url)})
                else:
                    got = _fetch_playwright(u["url"], f, timeout_ms=timeout_ms)
                    content = got.pop("content", "")
                    row.update({"fetch_ok": True, "fetch_method": f.name, **got})
            except Exception as exc:
                msg = f"{type(exc).__name__}: {exc}"
                row.update({"error": msg, "fetch_blocked": ("403" in msg or "FetchBlocked" in msg), "final_url": u["url"]})
            row["duration_ms"] = int((perf_counter() - start) * 1000)
            row["content_length"] = len(content)
            row.update(_json_diagnostics(content))
            if not row["json_detected"]:
                diag = diagnose_mercadolivre_html(content)
                row["html_diagnostics"] = {k: diag.get(k, row["html_diagnostics"][k]) for k in row["html_diagnostics"].keys()}
            row["useful_data_score"] = _compute_useful_data_score(row)
            if capture_base and content:
                ext = "json" if row["json_detected"] else "html"
                safe = re.sub(r"[^a-z0-9_-]", "_", f"{u['strategy']}_{f.name}".lower())
                target = capture_base / f"mercadolivre_{safe}.{ext}"
                target.write_text(content, encoding="utf-8")
                row["capture_path"] = str(target)
            attempts.append(row)

    best = max(attempts, key=lambda r: r.get("useful_data_score", -9999), default=None)
    recommended = best["url_strategy"] if best and best.get("useful_data_score", 0) > 0 else ""
    if best and best.get("useful_data_score", 0) >= 80:
        status = "OK"
    elif any((a.get("useful_data_score", 0) > 0 for a in attempts)):
        status = "WARN"
    elif any(a.get("fetch_ok") for a in attempts):
        status = "INCONCLUSIVE"
    else:
        status = "FAIL"
    for a in attempts:
        a["recommended"] = bool(recommended and a["url_strategy"] == recommended)
    return {"source": "mercadolivre", "query": query, "summary_status": status, "recommended_strategy": recommended, "attempts": attempts}
