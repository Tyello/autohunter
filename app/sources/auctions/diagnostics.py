from __future__ import annotations

import re
from typing import Any


def sanitize_html_preview(html: str, max_len: int = 800) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.I | re.S)).strip()
    return text[:max_len]


def build_auction_source_fetch_diagnostics(response: Any | None, html: str | None, url: str, reason: str | None = None) -> dict[str, Any]:
    raw = html or ""
    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.I | re.S)
    tokens = sorted(set(re.findall(r"https?://[^\"'\s<]+|/[a-z0-9_\-/]+(?:\?[^\"'\s<]*)?", raw, flags=re.I)))
    endpoint_like_patterns = ("/api/", "/ajax/", "/lotes/", "/item/", "/search", "/graphql")
    asset_ext_re = re.compile(r"\.(?:jpg|jpeg|png|gif|webp|svg|css|js|ico|woff2?|ttf|map)(?:\?|$)", flags=re.I)
    detail_re = re.compile(r"(?:https?://(?:www\.)?winleiloes\.com\.br)?/item/\d+/detalhes(?:\?[^\"'\s<]*)?", flags=re.I)
    lot_detail_candidates: list[str] = []
    lot_image_candidates: list[str] = []
    lot_document_candidates: list[str] = []
    asset_candidates: list[str] = []
    possible_api_endpoints: list[str] = []
    seen = set()
    for token in tokens:
        t = token.strip().rstrip(".,;)")
        low = t.lower()
        if not t or t in seen:
            continue
        seen.add(t)
        if detail_re.search(t):
            lot_detail_candidates.append(t)
        if low.endswith(".pdf") or ".pdf?" in low or "laudo" in low and ".pdf" in low:
            lot_document_candidates.append(t)
            continue
        if "cloudfront" in low or "/watermark/" in low or "/bens/" in low:
            if asset_ext_re.search(low) or "/watermark/" in low or "/bens/" in low:
                lot_image_candidates.append(t)
        is_asset = bool(asset_ext_re.search(low)) or any(k in low for k in ("cdnjs", "bootstrap", "jquery", "popper", "cloudfront"))
        if is_asset:
            asset_candidates.append(t)
            continue
        is_internal_win = low.startswith("https://www.winleiloes.com.br") or low.startswith("https://winleiloes.com.br") or low.startswith("/")
        if is_internal_win and any(p in low for p in endpoint_like_patterns):
            possible_api_endpoints.append(t)
    endpoints = possible_api_endpoints[:12]
    form_m = re.search(r"<form[^>]*action=[\"']([^\"']+)[\"'][^>]*>", raw, flags=re.I)
    method_m = re.search(r"<form[^>]*method=[\"']([^\"']+)[\"'][^>]*>", raw, flags=re.I)
    lower = raw.lower()
    indicators = [k for k in ["login", "cadastro", "access denied", "forbidden", "captcha", "cloudflare"] if k in lower]
    status_code = getattr(response, "status_code", None)
    final_url = str(getattr(response, "url", "") or "") or None
    headers = getattr(response, "headers", {}) or {}
    return {
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "content_type": headers.get("content-type"),
        "content_length": int(headers.get("content-length") or len(raw.encode("utf-8"))) if raw else 0,
        "html_title": re.sub(r"\s+", " ", (title_m.group(1).strip() if title_m else "")) or None,
        "reason": reason,
        "html_preview": sanitize_html_preview(raw, max_len=900),
        "hints": {
            "has_script_tags": bool(re.search(r"<script\b", raw, flags=re.I)),
            "possible_js_app": bool(re.search(r"__NEXT_DATA__|react-root|webpack|window\.__|vue|angular", raw, flags=re.I)),
            "possible_api_endpoints": endpoints,
            "asset_candidates": asset_candidates[:20],
            "lot_image_candidates": lot_image_candidates[:20],
            "lot_document_candidates": lot_document_candidates[:20],
            "lot_detail_candidates": lot_detail_candidates[:20],
            "form": {"action": form_m.group(1) if form_m else None, "method": (method_m.group(1).upper() if method_m else None)},
            "indicators": indicators,
        },
    }
