from __future__ import annotations

from typing import Any

from app.scrapers.framework import canonicalize_url
from app.sources.contract import NormalizedAd


DEFAULT_THRESHOLDS = {
    "min_overlap": 0.70,
    "max_critical_divergence_rate": 0.20,
}


def _index_by(items: list[NormalizedAd], key_fn) -> dict[Any, NormalizedAd]:
    out: dict[Any, NormalizedAd] = {}
    for ad in items:
        key = key_fn(ad)
        if key is None:
            continue
        out[key] = ad
    return out


def _match(v1: list[NormalizedAd], v2: list[NormalizedAd]) -> dict[int, int]:
    matches: dict[int, int] = {}
    used_v2: set[int] = set()

    def run_stage(key_fn):
        nonlocal matches, used_v2
        index_v2 = {}
        for j, b in enumerate(v2):
            if j in used_v2:
                continue
            key = key_fn(b)
            if key is None:
                continue
            index_v2.setdefault(key, j)
        for i, a in enumerate(v1):
            if i in matches:
                continue
            key = key_fn(a)
            if key is None:
                continue
            j = index_v2.get(key)
            if j is None:
                continue
            matches[i] = j
            used_v2.add(j)

    run_stage(lambda ad: canonicalize_url(ad.url) or None)
    run_stage(lambda ad: ad.external_id or None)
    run_stage(lambda ad: ad.fingerprint())
    return matches


def compare_ads(v1: list[NormalizedAd], v2: list[NormalizedAd], *, thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    cfg = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    matches = _match(v1, v2)
    matched_pairs = [(v1[i], v2[j]) for i, j in matches.items()]

    extras_v2 = max(0, len(v2) - len(matched_pairs))
    misses_v2 = max(0, len(v1) - len(matched_pairs))
    overlap = (len(matched_pairs) / max(1, len(v1))) if v1 else 1.0

    divergences = {
        "price": 0,
        "year": 0,
        "km": 0,
        "city": 0,
        "uf": 0,
        "images": 0,
    }
    for a, b in matched_pairs:
        if a.price != b.price:
            divergences["price"] += 1
        if a.year != b.year:
            divergences["year"] += 1
        if a.km != b.km:
            divergences["km"] += 1
        if (a.city or "").lower() != (b.city or "").lower():
            divergences["city"] += 1
        if (a.uf or "").upper() != (b.uf or "").upper():
            divergences["uf"] += 1
        if a.images_count != b.images_count:
            divergences["images"] += 1

    critical = divergences["price"] + divergences["year"]
    critical_rate = (critical / max(1, len(matched_pairs))) if matched_pairs else 0.0

    status = "PASS"
    if overlap < cfg["min_overlap"] or critical_rate > cfg["max_critical_divergence_rate"]:
        status = "FAIL"
    elif misses_v2 > 0 or extras_v2 > 0 or any(v > 0 for v in divergences.values()):
        status = "WARN"

    return {
        "status": status,
        "overlap": overlap,
        "matched": len(matched_pairs),
        "extras_v2": extras_v2,
        "misses_v2": misses_v2,
        "divergences": divergences,
        "thresholds": cfg,
    }
