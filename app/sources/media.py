from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def is_valid_http_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        p = urlparse(value)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False


def normalize_image_urls(images: Any) -> tuple[list[str], int, int]:
    """Return (cleaned_urls, duplicate_count, broken_count)."""
    candidates: list[Any] = []
    if isinstance(images, list):
        candidates = list(images)
    elif images is not None:
        candidates = [images]

    cleaned: list[str] = []
    seen: set[str] = set()
    duplicates = 0
    broken = 0

    for raw in candidates:
        candidate = raw
        if isinstance(raw, dict):
            candidate = raw.get("url") or raw.get("src") or raw.get("image") or raw.get("image_url")
        s = _clean_text(candidate)
        if not s or not is_valid_http_url(s):
            broken += 1
            continue
        if s in seen:
            duplicates += 1
            continue
        seen.add(s)
        cleaned.append(s)

    return cleaned, duplicates, broken


def derive_thumbnail_url(explicit_thumbnail: Any, images: Any) -> str | None:
    explicit = _clean_text(explicit_thumbnail)
    if explicit and is_valid_http_url(explicit):
        return explicit

    cleaned, _dup, _broken = normalize_image_urls(images)
    return cleaned[0] if cleaned else None

