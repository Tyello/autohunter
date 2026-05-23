from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_COMPARE_FIELDS = ("title", "price", "year", "km", "city", "uf", "url", "external_id", "thumbnail")


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

    field_diffs: list[dict[str, Any]] = []
    for key in matched_keys:
        left, right = v1_map[key], v2_map[key]
        diffs = {}
        for field in _COMPARE_FIELDS:
            if (left.get(field) or "") != (right.get(field) or ""):
                diffs[field] = {"v1": left.get(field) or "", "v2": right.get(field) or ""}
        if diffs:
            field_diffs.append({"key": key, "diff_fields": diffs, "v1": left, "v2": right})

    return {
        "v1_count": len(v1_norm),
        "v2_count": len(v2_norm),
        "matched_count": len(matched_keys),
        "only_v1_count": len(only_v1_keys),
        "only_v2_count": len(only_v2_keys),
        "field_diffs_count": len(field_diffs),
        "only_v1_examples": [v1_map[k] for k in only_v1_keys[:5]],
        "only_v2_examples": [v2_map[k] for k in only_v2_keys[:5]],
        "field_diff_examples": field_diffs[:5],
    }


def _summary_status(v1_count: int, v2_count: int) -> str:
    if v1_count > 0 and v2_count == 0:
        return "FAIL"
    if max(v1_count, v2_count, 1) and abs(v1_count - v2_count) / max(v1_count, v2_count, 1) > 0.30:
        return "WARN"
    return "OK"


def build_dual_run_report(source: str, search_url: str, v1_items: list[dict], v2_items: list[dict]) -> dict:
    compare = compare_items(v1_items, v2_items)
    report = {
        "source": (source or "").strip().lower(),
        "search_url": _to_clean_str(search_url),
        **compare,
    }
    report["summary_status"] = _summary_status(report["v1_count"], report["v2_count"])
    return report


def render_dual_run_report_markdown(report: dict) -> str:
    rpt = report or {}
    lines = [
        f"# Dual-run report: {rpt.get('source', '')}",
        "",
        f"- search_url: {rpt.get('search_url', '')}",
        f"- status: **{rpt.get('summary_status', 'UNKNOWN')}**",
        f"- v1_count: {rpt.get('v1_count', 0)}",
        f"- v2_count: {rpt.get('v2_count', 0)}",
        f"- matched_count: {rpt.get('matched_count', 0)}",
        f"- only_v1_count: {rpt.get('only_v1_count', 0)}",
        f"- only_v2_count: {rpt.get('only_v2_count', 0)}",
        f"- field_diffs_count: {rpt.get('field_diffs_count', 0)}",
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
