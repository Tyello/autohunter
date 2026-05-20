from __future__ import annotations

import re
from typing import Any


def sanitize_html_preview(html: str, max_len: int = 800) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<script[^>]*>.*?</script>", " ", html or "", flags=re.I | re.S)).strip()
    return text[:max_len]


def build_auction_source_fetch_diagnostics(response: Any | None, html: str | None, url: str, reason: str | None = None) -> dict[str, Any]:
    raw = html or ""
    title_m = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.I | re.S)
    endpoints = sorted(set(re.findall(r"https?://[^\"'\s<]+|/[a-z0-9_\-/]+(?:api|graphql|json|search|lotes|items)[^\"'\s<]*", raw, flags=re.I)))[:8]
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
            "form": {"action": form_m.group(1) if form_m else None, "method": (method_m.group(1).upper() if method_m else None)},
            "indicators": indicators,
        },
    }
