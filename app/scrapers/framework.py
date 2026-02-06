from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


_TRACKING_PARAMS = {
    # common tracking
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_name",
    "utm_date",
    "gclid",
    "gclsrc",
    "fbclid",
    "igshid",
    "msclkid",
    "wbraid",
    "gbraid",
    # marketplaces / share / ads
    "ref",
    "referrer",
    "ref_source",
    "refid",
    "source",
    "from",
    "origin",
    "tracking_id",
    "campaign_id",
    "ad_id",
    "adgroupid",
    "creative",
    # misc noisy params
    "srsltid",
    "spm",
    "pdp_filters",
    "utm_referrer",
}

_WS_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = _WS_RE.sub(" ", s)
    return s or None


def canonicalize_url(url: str | None, *, keep_query_keys: set[str] | None = None) -> str:
    """Drop tracking params and fragments to keep URLs stable for dedupe/matching."""
    if not url:
        return ""
    u = str(url).strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        keep = {k.lower() for k in (keep_query_keys or set())}
        q_out = []
        for k, v in parse_qsl(p.query or "", keep_blank_values=True):
            if not k:
                continue
            lk = k.lower()
            if lk in keep:
                q_out.append((k, v))
                continue
            if lk in _TRACKING_PARAMS:
                continue
            q_out.append((k, v))
        query = urlencode(q_out, doseq=True) if q_out else ""
        return urlunparse((p.scheme, p.netloc, p.path, p.params, query, ""))
    except Exception:
        return u.split("#", 1)[0]


def make_listing(
    *,
    source: str,
    external_id: str,
    url: str,
    title: Any = None,
    thumbnail_url: Any = None,
    price: Any = None,
    currency: Any = "BRL",
    location: Any = None,
    **extras: Any,
) -> dict:
    """Standard listing dict for ingestion.

    Keeps any extra fields (ex.: year/km) so the repo can encode them into title.
    """
    d: dict[str, Any] = {
        "source": (source or "").strip().lower(),
        "external_id": str(external_id).strip(),
        "url": canonicalize_url(url),
        "title": clean_text(title),
        "thumbnail_url": canonicalize_url(str(thumbnail_url).strip()) if thumbnail_url else None,
        "price": price,
        "currency": (str(currency).strip().upper() if currency else "BRL"),
        "location": clean_text(location),
    }

    for k, v in (extras or {}).items():
        if k in d:
            continue
        if v is None:
            continue
        d[k] = v

    return d


def _merge_best(existing: dict, incoming: dict) -> dict:
    out = dict(existing)
    for k, v in incoming.items():
        if k not in out or out.get(k) in (None, "", 0):
            if v not in (None, ""):
                out[k] = v

    if incoming.get("url"):
        out["url"] = incoming["url"]

    return out


def dedupe_listings(listings: Iterable[dict]) -> list[dict]:
    """Dedupe by (source, external_id) while merging best-effort fields."""
    by_key: dict[tuple[str, str], dict] = {}
    for it in listings or []:
        if not isinstance(it, dict):
            continue
        src = (it.get("source") or "").strip().lower()
        ext = (it.get("external_id") or "").strip()
        if not src or not ext:
            continue
        key = (src, ext)
        if key in by_key:
            by_key[key] = _merge_best(by_key[key], it)
        else:
            by_key[key] = it
    return list(by_key.values())
