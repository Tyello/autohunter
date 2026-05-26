from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

_COMPARE_FIELDS = ("title", "price", "year", "km", "city", "uf", "url", "external_id", "thumbnail")
_ENRICHMENT_FIELDS = {"year", "km", "city", "uf", "thumbnail"}


def _to_clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_number_like(value: Any) -> str:
    raw = _to_clean_str(value)
    if not raw:
        return ""
    cleaned = re.sub(r"[^\d,.-]", "", raw)
    if not cleaned:
        return ""
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") >= 1 and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "")
    try:
        d = Decimal(cleaned)
    except InvalidOperation:
        return raw
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


def _normalize_url(value: Any) -> str:
    raw = _to_clean_str(value)
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=False)))
        path = re.sub(r"/+", "/", parts.path or "").rstrip("/") or "/"
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))
    except Exception:
        return raw


def normalize_item_for_compare(item: dict) -> dict:
    payload = item or {}
    city_raw = payload.get("city")
    uf_raw = payload.get("uf") or payload.get("state")
    if (not city_raw or not uf_raw) and payload.get("location"):
        parts = [p.strip() for p in str(payload.get("location") or "").split(",") if p.strip()]
        if not city_raw and parts:
            city_raw = parts[0]
        if not uf_raw and len(parts) > 1:
            uf_raw = parts[-1]

    normalized = {
        "title": _to_clean_str(payload.get("title")),
        "price": _normalize_number_like(payload.get("price")),
        "year": _normalize_number_like(payload.get("year")),
        "km": _normalize_number_like(payload.get("km") or payload.get("mileage_km")),
        "city": _to_clean_str(city_raw),
        "uf": _to_clean_str(uf_raw),
        "url": _normalize_url(payload.get("url")),
        "external_id": _to_clean_str(payload.get("external_id") or payload.get("id")),
        "thumbnail": _to_clean_str(payload.get("thumbnail") or payload.get("thumbnail_url")),
    }
    return normalized


def _item_key(item: dict) -> str:
    external_id = item.get("external_id") or ""
    if external_id:
        return f"id:{external_id.lower()}"

    url = item.get("url") or ""
    if url:
        return f"url:{url}"

    title = (item.get("title") or "").lower()
    price = item.get("price") or ""
    year = item.get("year") or ""
    if title or price or year:
        return f"fallback:{title}|{price}|{year}"

    return "fallback:"


def compare_items(v1_items: list[dict], v2_items: list[dict]) -> dict:
    v1_norm = [normalize_item_for_compare(x) for x in (v1_items or [])]
    v2_norm = [normalize_item_for_compare(x) for x in (v2_items or [])]

    v1_map: dict[str, dict] = {}
    v2_map: dict[str, dict] = {}
    for item in v1_norm:
        v1_map.setdefault(_item_key(item), item)
    for item in v2_norm:
        v2_map.setdefault(_item_key(item), item)

    keys_v1 = set(v1_map)
    keys_v2 = set(v2_map)
    matched_keys = sorted(keys_v1 & keys_v2)
    only_v1_keys = sorted(keys_v1 - keys_v2)
    only_v2_keys = sorted(keys_v2 - keys_v1)

    v1_unique_count = len(v1_map)
    v2_unique_count = len(v2_map)
    field_diffs: list[dict[str, Any]] = []
    blocking_field_diffs_count = 0
    non_blocking_field_diffs_count = 0
    enrichment_field_diffs_count = 0
    blocking_examples: list[dict[str, Any]] = []
    enrichment_examples: list[dict[str, Any]] = []
    for key in matched_keys:
        left, right = v1_map[key], v2_map[key]
        diffs = {}
        for field in _COMPARE_FIELDS:
            if (left.get(field) or "") != (right.get(field) or ""):
                classification = "blocking"
                if field in _ENRICHMENT_FIELDS and not (left.get(field) or "") and (right.get(field) or ""):
                    classification = "v2_enrichment"
                diffs[field] = {"v1": left.get(field) or "", "v2": right.get(field) or "", "classification": classification}
                if classification == "blocking":
                    blocking_field_diffs_count += 1
                elif classification == "v2_enrichment":
                    enrichment_field_diffs_count += 1
                else:
                    non_blocking_field_diffs_count += 1
        if diffs:
            diff_entry = {"key": key, "diff_fields": diffs, "v1": left, "v2": right}
            field_diffs.append(diff_entry)
            if any(v.get("classification") == "blocking" for v in diffs.values()) and len(blocking_examples) < 5:
                blocking_examples.append(diff_entry)
            if all(v.get("classification") == "v2_enrichment" for v in diffs.values()) and len(enrichment_examples) < 5:
                enrichment_examples.append(diff_entry)

    return {
        "v1_count": len(v1_norm),
        "v2_count": len(v2_norm),
        "v1_unique_count": v1_unique_count,
        "v2_unique_count": v2_unique_count,
        "v1_duplicate_count": max(0, len(v1_norm) - v1_unique_count),
        "v2_duplicate_count": max(0, len(v2_norm) - v2_unique_count),
        "matched_count": len(matched_keys),
        "only_v1_count": len(only_v1_keys),
        "only_v2_count": len(only_v2_keys),
        "field_diffs_count": len(field_diffs),
        "blocking_field_diffs_count": blocking_field_diffs_count,
        "non_blocking_field_diffs_count": non_blocking_field_diffs_count,
        "enrichment_field_diffs_count": enrichment_field_diffs_count,
        "only_v1_examples": [v1_map[k] for k in only_v1_keys[:5]],
        "only_v2_examples": [v2_map[k] for k in only_v2_keys[:5]],
        "blocking_field_diff_examples": blocking_examples,
        "enrichment_diff_examples": enrichment_examples,
        "field_diff_examples": field_diffs[:5],
    }




def _extract_v2_metrics(v2_metrics: Any) -> dict[str, Any]:
    if not v2_metrics:
        return {}
    keys = (
        "fetch_method",
        "fetch_blocked",
        "fetch_error",
        "raw_items_found",
        "items_parsed",
        "items_valid",
        "items_invalid",
        "parse_errors",
        "total_duration_ms",
        "circuit_breaker_state",
    )
    out: dict[str, Any] = {}
    for key in keys:
        value = getattr(v2_metrics, key, None)
        if value is not None:
            out[key] = value
    return out


def diagnose_mercadolivre_html(raw_content: str) -> dict[str, Any]:
    html = raw_content or ""
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    canonical = (soup.select_one("link[rel='canonical']") or {}).get("href", "").strip() if soup.select_one("link[rel='canonical']") else ""
    og_url = (soup.select_one("meta[property='og:url']") or {}).get("content", "").strip() if soup.select_one("meta[property='og:url']") else ""

    mlb_links = []
    vehicle_links = []
    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").strip()
        if "/MLB-" in href:
            mlb_links.append(href)
        if "/veiculos/" in href:
            vehicle_links.append(href)

    signals: list[str] = []
    body_text = soup.get_text(" ", strip=True).lower()
    if "mercado livre" in title.lower() or "mercadolivre.com.br" in html.lower():
        signals.append("mercado_livre_page")
    if "access to this page has been denied" in body_text:
        signals.append("access_denied")
    if "captcha" in body_text:
        signals.append("captcha")
    if "bot challenge" in body_text or "are you human" in body_text:
        signals.append("bot_challenge")
    if "consent" in body_text or "cookies" in body_text and "aceitar" in body_text:
        signals.append("consent")
    if "não encontramos resultados" in body_text or "nao encontramos resultados" in body_text:
        signals.append("zero_results")
    if "sem resultados" in body_text or "no results" in body_text:
        signals.append("no_results")
    if soup.select_one("script[type='application/ld+json']"):
        signals.append("has_json_ld")
    if soup.select_one("script#__NEXT_DATA__"):
        signals.append("has_next_data")
    if "window.__PRELOADED_STATE__" in html:
        signals.append("has_preloaded_state")
    if mlb_links:
        signals.append("has_mlb_links")
    if vehicle_links:
        signals.append("has_vehicle_links")

    return {
        "content_length": len(html),
        "title": title,
        "canonical_url": canonical,
        "og_url": og_url,
        "selector_counts": {
            "li.ui-search-layout__item": len(soup.select("li.ui-search-layout__item")),
            "div.ui-search-result": len(soup.select("div.ui-search-result")),
            "div[class*='item__container']": len(soup.select("div[class*='item__container']")),
            "article": len(soup.select("article")),
            "li_has_mlb_link": len(soup.select("li a[href*='/MLB-']")),
            "a_mlb_links": len(mlb_links),
            "a_vehicle_links": len(vehicle_links),
        },
        "signals": list(dict.fromkeys(signals)),
        "sample_links": list(dict.fromkeys((mlb_links + vehicle_links)))[:5],
    }


def build_mercadolivre_probe_hints(v2_raw_items_found: Any, html_diagnostics: dict[str, Any] | None) -> list[str]:
    if v2_raw_items_found != 0 or not html_diagnostics:
        return []
    selectors = (html_diagnostics or {}).get("selector_counts", {}) or {}
    signals = set((html_diagnostics or {}).get("signals", []) or [])
    card_count = int(selectors.get("li.ui-search-layout__item", 0)) + int(selectors.get("div.ui-search-result", 0)) + int(selectors.get("div[class*='item__container']", 0))
    hints: list[str] = []
    if card_count == 0 and int(html_diagnostics.get("content_length", 0)) > 5000:
        hints.append("ml_html_structure_changed_or_spa")
    if int(selectors.get("a_mlb_links", 0)) > 0 and card_count == 0:
        hints.append("ml_links_present_but_card_selectors_missing")
    if "zero_results" in signals or "no_results" in signals:
        hints.append("ml_zero_results_page")
    if signals.intersection({"access_denied", "captcha", "bot_challenge"}):
        hints.append("ml_probe_blocked_or_challenged")
    if int(selectors.get("a_vehicle_links", 0)) > 0:
        hints.append("ml_vehicle_links_present_extractor_gap")
    return list(dict.fromkeys(hints))


def _build_diagnostics(
    *,
    query: str,
    search_url: str,
    v1_items: list[dict],
    v2_items: list[dict],
    v1_error: str,
    v2_error: str,
    v2_blocked: bool,
    v2_warnings: list[str],
    v2_metrics: Any = None,
    fetch_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parts = urlsplit(_to_clean_str(search_url))
    v2_metrics_dict = _extract_v2_metrics(v2_metrics)

    hints: list[str] = []
    v1_count = len(v1_items or [])
    v2_count = len(v2_items or [])
    raw_items_found = v2_metrics_dict.get("raw_items_found")

    if v1_count == 0 and v2_count == 0:
        hints.extend([
            "both_paths_zero_items",
            "try_broader_query_or_explicit_url",
            "check_ml_fetch_or_parser",
            "inspect_v2_metrics_raw_items_found",
            "not_safe_to_flip_to_v2",
        ])
        if not _to_clean_str(v1_error) and not _to_clean_str(v2_error):
            hints.append("dual_run_inconclusive_not_parity")

    if v2_count == 0 and isinstance(raw_items_found, int):
        if raw_items_found > 0:
            hints.extend(["v2_extracted_raw_but_parsed_zero", "likely_v2_parse_listing_gap"])
        elif raw_items_found == 0:
            hints.extend(["v2_extracted_zero_raw_items", "likely_fetch_or_extract_gap"])
            hints.extend(build_mercadolivre_probe_hints(raw_items_found, (fetch_probe or {}).get("html_diagnostics")))

    if v2_blocked:
        hints.append("v2_blocked")

    # remove duplicados preservando ordem
    hints = list(dict.fromkeys(hints))

    return {
        "query": _to_clean_str(query),
        "search_url": _to_clean_str(search_url),
        "url_host": parts.netloc or "",
        "url_path": parts.path or "",
        "v1_executed": True,
        "v2_executed": True,
        "v1_empty": v1_count == 0,
        "v2_empty": v2_count == 0,
        "v1_error": _to_clean_str(v1_error),
        "v2_error": _to_clean_str(v2_error),
        "v2_blocked": bool(v2_blocked),
        "v2_warnings": list(v2_warnings or []),
        "v2_metrics": v2_metrics_dict,
        "hints": hints,
        **({"fetch_probe": fetch_probe} if fetch_probe else {}),
    }
def _summary_status_and_reason(compare: dict[str, Any], *, v1_error: str = "", v2_error: str = "") -> tuple[str, str]:
    v1_count = int(compare.get("v1_count", 0))
    v2_count = int(compare.get("v2_count", 0))
    v1_unique_count = int(compare.get("v1_unique_count", v1_count))
    v2_unique_count = int(compare.get("v2_unique_count", v2_count))
    only_v1_count = int(compare.get("only_v1_count", 0))
    only_v2_count = int(compare.get("only_v2_count", 0))
    blocking_diffs = int(compare.get("blocking_field_diffs_count", 0))
    if v1_error or v2_error:
        return "FAIL", "path_execution_error"
    if v1_count == 0 and v2_count == 0:
        return "INCONCLUSIVE", "both_paths_returned_zero_items"
    if v1_count > 0 and v2_count == 0:
        return "FAIL", "v2_returned_zero_items_while_v1_found_items"
    if v1_count == 0 and v2_count > 0:
        return "WARN", "v1_returned_zero_items_while_v2_found_items"
    if only_v1_count > 0 or only_v2_count > 0:
        return "WARN", "unique_id_mismatch_between_paths"
    if blocking_diffs > 0:
        return "WARN", "blocking_field_diffs_between_paths"
    if only_v1_count == 0 and only_v2_count == 0 and v1_unique_count == v2_unique_count and blocking_diffs == 0:
        if int(compare.get("enrichment_field_diffs_count", 0)) > 0:
            return "OK", "unique_parity_ok_enrichment_only"
        return "OK", "unique_parity_ok"
    if max(v1_count, v2_count, 1) and abs(v1_count - v2_count) / max(v1_count, v2_count, 1) > 0.30:
        return "WARN", "count_difference_above_threshold"
    return "OK", "counts_within_threshold"


def build_dual_run_report(
    source: str,
    search_url: str,
    v1_items: list[dict],
    v2_items: list[dict],
    *,
    query: str = "",
    v1_error: str = "",
    v2_error: str = "",
    v2_blocked: bool = False,
    v2_warnings: list[str] | None = None,
    v2_metrics: Any = None,
    fetch_probe: dict[str, Any] | None = None,
) -> dict:
    compare = compare_items(v1_items, v2_items)
    report = {
        "source": (source or "").strip().lower(),
        "search_url": _to_clean_str(search_url),
        **compare,
    }
    status, reason = _summary_status_and_reason(report, v1_error=_to_clean_str(v1_error), v2_error=_to_clean_str(v2_error))
    report["summary_status"] = status
    report["summary_reason"] = reason
    if v1_error:
        report["v1_error"] = _to_clean_str(v1_error)
    if v2_error:
        report["v2_error"] = _to_clean_str(v2_error)
    report["v2_blocked"] = bool(v2_blocked)
    report["v2_warnings"] = list(v2_warnings or [])[:5]
    report["diagnostics"] = _build_diagnostics(
        query=query,
        search_url=search_url,
        v1_items=v1_items,
        v2_items=v2_items,
        v1_error=v1_error,
        v2_error=v2_error,
        v2_blocked=v2_blocked,
        v2_warnings=list(v2_warnings or []),
        v2_metrics=v2_metrics,
        fetch_probe=fetch_probe,
    )
    hints = report["diagnostics"].get("hints", [])
    if report.get("v1_duplicate_count", 0) > 0:
        hints.append("v1_duplicates_detected")
    if report.get("only_v1_count", 0) == 0 and report.get("only_v2_count", 0) == 0 and report.get("v1_unique_count", 0) == report.get("v2_unique_count", -1):
        hints.append("unique_parity_ok")
    if report.get("enrichment_field_diffs_count", 0) > 0 and any(
        (diff.get("classification") == "v2_enrichment" and field == "year")
        for ex in report.get("field_diff_examples", [])
        for field, diff in (ex.get("diff_fields") or {}).items()
    ):
        hints.append("v2_enriched_year_from_title")
    if report.get("summary_status") == "OK" and report.get("v1_duplicate_count", 0) > 0 and report.get("only_v1_count", 0) == 0 and report.get("only_v2_count", 0) == 0:
        hints.append("not_blocking_for_v2_flip_candidate")
    report["diagnostics"]["hints"] = list(dict.fromkeys(hints))
    return report


def render_dual_run_report_markdown(report: dict) -> str:
    rpt = report or {}
    lines = [
        f"# Dual-run report: {rpt.get('source', '')}",
        "",
        f"- search_url: {rpt.get('search_url', '')}",
        f"- status: **{rpt.get('summary_status', 'UNKNOWN')}**",
        f"- summary_reason: {rpt.get('summary_reason', '')}",
        f"- v1_count: {rpt.get('v1_count', 0)}",
        f"- v1_unique_count: {rpt.get('v1_unique_count', 0)}",
        f"- v1_duplicate_count: {rpt.get('v1_duplicate_count', 0)}",
        f"- v2_count: {rpt.get('v2_count', 0)}",
        f"- v2_unique_count: {rpt.get('v2_unique_count', 0)}",
        f"- v2_duplicate_count: {rpt.get('v2_duplicate_count', 0)}",
        f"- matched_count: {rpt.get('matched_count', 0)}",
        f"- only_v1_count: {rpt.get('only_v1_count', 0)}",
        f"- only_v2_count: {rpt.get('only_v2_count', 0)}",
        f"- field_diffs_count: {rpt.get('field_diffs_count', 0)}",
        f"- blocking_field_diffs_count: {rpt.get('blocking_field_diffs_count', 0)}",
        f"- non_blocking_field_diffs_count: {rpt.get('non_blocking_field_diffs_count', 0)}",
        f"- enrichment_field_diffs_count: {rpt.get('enrichment_field_diffs_count', 0)}",
        f"- v2_blocked: {rpt.get('v2_blocked', False)}",
        f"- v2_warnings: {rpt.get('v2_warnings', [])}",
        f"- diagnostics_hints: {(rpt.get('diagnostics') or {}).get('hints', [])}",
        f"- v2_metrics: {(rpt.get('diagnostics') or {}).get('v2_metrics', {})}",
        f"- fetch_probe: {(rpt.get('diagnostics') or {}).get('fetch_probe', {})}",
        *( [f"- v1_error: {rpt.get('v1_error')}" ] if rpt.get("v1_error") else [] ),
        *( [f"- v2_error: {rpt.get('v2_error')}" ] if rpt.get("v2_error") else [] ),
        "",
        "## only_v1_examples",
        "```json",
        json.dumps(rpt.get("only_v1_examples", []), ensure_ascii=False, indent=2),
        "```",
        "",
        "## only_v2_examples",
        "```json",
        json.dumps(rpt.get("only_v2_examples", []), ensure_ascii=False, indent=2),
        "```",
        "",
        "## field_diff_examples",
        "```json",
        json.dumps(rpt.get("field_diff_examples", []), ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines)
