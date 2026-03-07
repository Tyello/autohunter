from __future__ import annotations

import re
from typing import Any, Iterable

from app.scrapers.framework import (
    canonicalize_listing_url,
    canonicalize_url,
    clean_text,
    dedupe_listings,
    make_listing,
)
from app.scrapers.diagnostics import current_diagnostics


_RE_MLB = re.compile(r"\b(MLB)[- ]?(\d{6,})\b", re.I)
_RE_FB = re.compile(r"/marketplace/item/(\d+)")
_RE_CHAVES = re.compile(r"/id-(\d+)")


def _fallback_external_id(source: str, url: str) -> str:
    """Best-effort fallback when a scraper couldn't extract a stable external_id."""
    u = url or ""

    if not u:
        return ""

    s = (source or "").strip().lower()

    if s == "mercadolivre":
        m = _RE_MLB.search(u)
        if m:
            return f"MLB{m.group(2)}"

    if s == "facebook_marketplace":
        m = _RE_FB.search(u)
        if m:
            return m.group(1)

    if s == "chavesnamao":
        m = _RE_CHAVES.search(u)
        if m:
            return m.group(1)

    # generic fallback: use the canonicalized URL itself
    return canonicalize_listing_url(u) or u


_CORE_KEYS = {
    "source",
    "external_id",
    "url",
    "title",
    "thumbnail_url",
    "price",
    "currency",
    "location",
}


def finalize_listings(source: str, raw_items: Iterable[Any]) -> list[dict]:
    """Normalize + harden scraper output.

    Guarantees:
    - every item is a dict with at least: source, external_id, url, currency
    - url is canonicalized (drops tracking params/fragments)
    - strings are stripped and normalized
    - deduped by (source, external_id)

    Preserves extras like `year` and `km` so the repo can encode them into title.
    """

    diag = current_diagnostics()

    src = (source or "").strip().lower()
    out: list[dict] = []

    for it in raw_items or []:
        if diag is not None:
            diag.inc("items_parsed")
        if not isinstance(it, dict):
            if diag is not None:
                diag.inc("items_drop_non_dict")
            continue

        url = canonicalize_listing_url(it.get("url") or "")
        if not url:
            if diag is not None:
                diag.inc("items_drop_no_url")
            continue

        ext = (it.get("external_id") or "").strip()
        if not ext:
            ext = _fallback_external_id(src, url)
        if not ext:
            if diag is not None:
                diag.inc("items_drop_no_external_id")
            continue

        currency = (it.get("currency") or "BRL")
        title = clean_text(it.get("title"))
        location = clean_text(it.get("location"))
        thumb = it.get("thumbnail_url")

        extras = {k: v for k, v in it.items() if k not in _CORE_KEYS and v is not None}

        out.append(
            make_listing(
                source=src,
                external_id=ext,
                url=url,
                title=title,
                thumbnail_url=thumb,
                price=it.get("price"),
                currency=currency,
                location=location,
                **extras,
            )
        )

    before = len(out)
    deduped = dedupe_listings(out)
    after = len(deduped)

    if diag is not None:
        if before >= after:
            diag.inc("items_deduped", before - after)
        diag.inc("items_final", after)

        # Field quality signals (cheap)
        missing_price = 0
        missing_title = 0
        for it in deduped:
            if not it.get("price"):
                missing_price += 1
            if not (it.get("title") or "").strip():
                missing_title += 1
        if missing_price:
            diag.inc("items_missing_price", missing_price)
        if missing_title:
            diag.inc("items_missing_title", missing_title)

    return deduped
