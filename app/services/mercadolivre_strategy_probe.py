from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from app.scrapers.base import FetchBlocked
from app.scrapers.scraper_base.fetcher import unified_fetch
from app.scrapers.sources.mercadolivre import MercadoLivreScraper
from app.sources import get_source
from app.sources.types import ScrapeContext


@dataclass
class ProbeOptions:
    include_browser: bool = False
    capture_dir: str | None = None
    timeout_ms: int = 30000


def _slugify(text: str) -> str:
    raw = (text or "").strip().lower()
    raw = re.sub(r"[^\w\s-]+", " ", raw, flags=re.UNICODE)
    return re.sub(r"[\s_]+", "-", raw).strip("-") or "carro"


def _infer_brand_model(query: str) -> tuple[str | None, str | None]:
    q = _slugify(query)
    model_to_brand = {"civic": "honda", "golf": "volkswagen", "corolla": "toyota"}
    parts = q.split("-")
    if not parts:
        return None, None
    brand = model_to_brand.get(parts[0])
    if brand:
        return brand, parts[0]
    return None, None


def build_mercadolivre_strategy_urls(query: str, external_id: str | None = None) -> list[dict[str, str]]:
    slug = _slugify(query)
    plugin = get_source("mercadolivre")
    plugin_url = plugin.build_url(query) if plugin else f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{slug}"
    v2_url = MercadoLivreScraper().build_search_url(query)
    urls: list[dict[str, str]] = [
        {"strategy": "plugin_build_url", "url": plugin_url, "kind": "html", "source": "plugin"},
        {"strategy": "v2_build_search_url", "url": v2_url, "kind": "api", "source": "v2"},
        {"strategy": "lista_generic_slug", "url": f"https://lista.mercadolivre.com.br/{slug}", "kind": "html", "source": "manual"},
        {"strategy": "lista_vehicle_slug", "url": f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{slug}", "kind": "html", "source": "manual"},
        {"strategy": "api_with_category", "url": f"https://api.mercadolibre.com/sites/MLB/search?q={quote_plus(query)}&category=MLB1743", "kind": "api", "source": "manual"},
        {"strategy": "api_without_category", "url": f"https://api.mercadolibre.com/sites/MLB/search?q={quote_plus(query)}", "kind": "api", "source": "manual"},
        {"strategy": "api_category_first", "url": f"https://api.mercadolibre.com/sites/MLB/search?category=MLB1743&q={quote_plus(query)}", "kind": "api", "source": "manual"},
    ]
    brand, model = _infer_brand_model(query)
    if brand and model:
        urls.append({"strategy": "lista_vehicle_brand_model", "url": f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{brand}/{model}", "kind": "html", "source": "derived"})
    if external_id:
        clean = re.sub(r"[^A-Za-z0-9]", "", external_id).upper().replace("MLB", "")
        urls.append({"strategy": "vip_from_external_id", "url": f"https://carro.mercadolivre.com.br/MLB-{clean}-_JM", "kind": "vip", "source": "derived"})
    return urls


def _analyze_content(content: str) -> dict[str, Any]:
    data = {"json_detected": False, "json_results_count": None, "json_error_message": "", "html_diagnostics": {"title": "", "canonical_url": "", "og_url": "", "selector_counts": {}, "signals": [], "sample_links": []}}
    try:
        payload = json.loads(content)
        data["json_detected"] = True
        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            data["json_results_count"] = len(payload["results"])
        return data
    except Exception as e:
        data["json_error_message"] = str(e)

    soup = BeautifulSoup(content or "", "lxml")
    title = (soup.title.get_text(strip=True) if soup.title else "")
    canonical = soup.select_one('link[rel="canonical"]')
    og = soup.select_one('meta[property="og:url"]')
    links = [a.get("href", "") for a in soup.select("a[href]") if a.get("href")][:5]
    counts = {
        "cards_count": len(soup.select("li.ui-search-layout__item,div.ui-search-result,article")),
        "a_mlb_links": len(soup.select("a[href*='MLB-']")),
        "a_vehicle_links": len(soup.select("a[href*='carro.mercadolivre.com.br']")),
    }
    signals = []
    low = (content or "").lower()
    if "mercado livre" in low:
        signals.append("mercado_livre_page")
    if "__preloaded_state__" in low:
        signals.append("has_preloaded_state")
    if 'application/ld+json' in low:
        signals.append("has_json_ld")
    if any(s in low for s in ["captcha", "access denied", "challenge"]):
        signals.append("blocked_challenge")
    data["html_diagnostics"] = {
        "title": title,
        "canonical_url": canonical.get("href", "") if canonical else "",
        "og_url": og.get("content", "") if og else "",
        "selector_counts": counts,
        "signals": signals,
        "sample_links": links,
    }
    return data


def _score(result: dict[str, Any]) -> int:
    s = 0
    jc = result.get("json_results_count") or 0
    counts = result["html_diagnostics"]["selector_counts"]
    signals = set(result["html_diagnostics"]["signals"])
    if jc > 0:
        s += 100
    if counts.get("cards_count", 0) > 0:
        s += 80
    if counts.get("a_mlb_links", 0) > 0:
        s += 60
    if counts.get("a_vehicle_links", 0) > 0:
        s += 40
    if "has_preloaded_state" in signals or "has_json_ld" in signals:
        s += 20
    if result.get("fetch_blocked") or "blocked_challenge" in signals:
        s -= 100
    if counts.get("cards_count", 0) == 0 and counts.get("a_mlb_links", 0) == 0 and result.get("content_length", 0) > 3000:
        s -= 30
    return s


def run_probe(query: str, options: ProbeOptions, external_id: str | None = None, limit_strategies: int | None = None) -> dict[str, Any]:
    fetch_strategies = ["unified_fetch", "curl_cffi_direct"] + (["playwright_domcontentloaded", "playwright_networkidle", "playwright_wait_scroll"] if options.include_browser else [])
    url_rows = build_mercadolivre_strategy_urls(query, external_id=external_id)
    if limit_strategies:
        url_rows = url_rows[:limit_strategies]
    attempts = []
    for u in url_rows:
        for f in fetch_strategies:
            attempts.append(_run_attempt(u, f, options))
    best = max(attempts, key=lambda x: x["useful_data_score"]) if attempts else None
    if best and best["useful_data_score"] > 0:
        for a in attempts:
            a["recommended"] = a is best
        recommended = f"{best['url_strategy']}:{best['fetch_strategy']}"
    else:
        recommended = ""
    max_score = max([a["useful_data_score"] for a in attempts], default=-999)
    if max_score >= 80:
        status = "OK"
    elif max_score > 0:
        status = "WARN"
    elif any(a["fetch_ok"] for a in attempts):
        status = "INCONCLUSIVE"
    else:
        status = "FAIL"
    return {"query": query, "summary_status": status, "recommended_strategy": recommended, "attempts": attempts}


def _run_attempt(url_row: dict[str, str], fetch_strategy: str, options: ProbeOptions) -> dict[str, Any]:
    started = time.time()
    base = {"url_strategy": url_row["strategy"], "fetch_strategy": fetch_strategy, "url": url_row["url"], "fetch_ok": False, "fetch_blocked": False, "http_status": None, "error": "", "fetch_method": "", "duration_ms": 0, "final_url": "", "content_type": "", "content_length": 0, "json_detected": False, "json_results_count": None, "json_error_message": "", "html_diagnostics": {"title": "", "canonical_url": "", "og_url": "", "selector_counts": {}, "signals": [], "sample_links": []}, "useful_data_score": 0, "recommended": False}
    content = ""
    try:
        if fetch_strategy == "unified_fetch":
            ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=False, browser_timeout_ms=options.timeout_ms)
            fr = unified_fetch(url_row["url"], ctx, source="mercadolivre")
            content = fr.content
            base.update({"fetch_ok": True, "fetch_method": fr.method, "final_url": fr.final_url})
        elif fetch_strategy == "curl_cffi_direct":
            try:
                from curl_cffi import requests as cffi_requests
            except Exception:
                base["error"] = "curl_cffi_not_installed"
                base["duration_ms"] = int((time.time() - started) * 1000)
                return base
            resp = cffi_requests.get(url_row["url"], impersonate="chrome", timeout=options.timeout_ms / 1000, headers={"User-Agent": "Mozilla/5.0"})
            base["http_status"] = resp.status_code
            content = resp.text
            base.update({"fetch_ok": True, "fetch_method": "curl_cffi_direct", "fetch_blocked": resp.status_code >= 400, "final_url": str(resp.url), "content_type": resp.headers.get("content-type", "")})
        else:
            base["error"] = "playwright_disabled_without_include_browser"
            base["duration_ms"] = int((time.time() - started) * 1000)
            return base
    except FetchBlocked as e:
        base["fetch_blocked"] = True
        base["error"] = str(e)
    except Exception as e:
        base["error"] = str(e)

    base["duration_ms"] = int((time.time() - started) * 1000)
    base["content_length"] = len(content or "")
    if content:
        base.update(_analyze_content(content))
    base["useful_data_score"] = _score(base)
    if options.capture_dir and content:
        cpath = _capture(options.capture_dir, base["url_strategy"], base["fetch_strategy"], content, base["json_detected"])
        base["capture_path"] = str(cpath)
    return base


def _capture(capture_dir: str, url_strategy: str, fetch_strategy: str, content: str, is_json: bool) -> Path:
    out_dir = Path(capture_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", f"mercadolivre_{url_strategy}_{fetch_strategy}")
    suffix = ".json" if is_json else ".html"
    path = out_dir / f"{safe}{suffix}"
    path.write_text(content, encoding="utf-8")
    return path
