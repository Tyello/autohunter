from __future__ import annotations

import re
import unicodedata
from collections import Counter

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.fipe_catalog_entry import FipeCatalogEntry
from app.services.fipe_monthly_sync_service import normalize_fipe_month

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"de", "do", "da", "dos", "das", "e", "the", "sedan", "hatch", "coupe"}
_IMPORTANT_SHORT_TOKENS = {"si", "xr", "ex", "lx", "gti", "gli", "tsi", "mpi", "v6", "v8", "cvt"}


def normalize_vehicle_text(value: str | None) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("/", " ").replace("-", " ").replace(".", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def vehicle_tokens(value: str | None) -> list[str]:
    return [t for t in _WORD_RE.findall(normalize_vehicle_text(value)) if t]


def important_vehicle_tokens(value: str | None) -> set[str]:
    out: set[str] = set()
    for tok in vehicle_tokens(value):
        if tok in _STOPWORDS:
            continue
        if len(tok) <= 1 and not tok.isdigit():
            continue
        if len(tok) == 2 and tok not in _IMPORTANT_SHORT_TOKENS and not tok.isdigit():
            continue
        out.add(tok)
    return out


def build_listing_fipe_query(listing) -> dict:
    return {
        "make": normalize_vehicle_text(getattr(listing, "make", None)),
        "model": normalize_vehicle_text(getattr(listing, "model", None)),
        "version": normalize_vehicle_text(getattr(listing, "version", None)),
        "year": getattr(listing, "year", None),
        "fuel_type": normalize_vehicle_text(getattr(listing, "fuel_type", None)),
        "transmission": normalize_vehicle_text(getattr(listing, "transmission", None)),
        "body_type": normalize_vehicle_text(getattr(listing, "body_type", None)),
        "doors": getattr(listing, "doors", None),
    }


def _ensure_month(db: Session, reference_month: str | None) -> str:
    if reference_month:
        return normalize_fipe_month(reference_month)
    row = db.query(FipeCatalogEntry.reference_month).order_by(FipeCatalogEntry.reference_month.desc()).first()
    if not row:
        raise ValueError("Sem dados no catálogo FIPE staging.")
    return row[0]


def find_fipe_catalog_candidates(db: Session, *, listing, reference_month: str, limit: int = 10) -> list[FipeCatalogEntry]:
    query = build_listing_fipe_query(listing)
    month = normalize_fipe_month(reference_month)
    limit = max(1, min(50, int(limit)))
    cap = 250

    base = db.query(FipeCatalogEntry).filter(
        FipeCatalogEntry.reference_month == month,
        FipeCatalogEntry.vehicle_type == "car",
    )

    brand = query.get("make")
    year = query.get("year")
    model_tokens = sorted(important_vehicle_tokens(query.get("model")))
    version_tokens = sorted(important_vehicle_tokens(query.get("version")))
    all_tokens = list(dict.fromkeys(model_tokens + version_tokens))[:6]

    def _fetch(extra_filters):
        q = base
        for flt in extra_filters:
            q = q.filter(flt)
        return q.order_by(FipeCatalogEntry.model_year.desc().nullslast()).limit(cap).all()

    candidates: list[FipeCatalogEntry] = []
    if brand and query.get("model"):
        candidates = _fetch([FipeCatalogEntry.brand_name.ilike(f"%{brand}%"), FipeCatalogEntry.model_name.ilike(f"%{query['model']}%")])

    if not candidates and brand and year:
        candidates = _fetch([FipeCatalogEntry.brand_name.ilike(f"%{brand}%"), FipeCatalogEntry.model_year.in_([year, year - 1, year + 1])])

    if not candidates and brand and all_tokens:
        token_filters = [FipeCatalogEntry.model_name.ilike(f"%{tok}%") for tok in all_tokens[:4]]
        candidates = _fetch([FipeCatalogEntry.brand_name.ilike(f"%{brand}%"), or_(*token_filters)])

    if not candidates and year and all_tokens:
        token_filters = [FipeCatalogEntry.model_name.ilike(f"%{tok}%") for tok in all_tokens[:4]]
        candidates = _fetch([FipeCatalogEntry.model_year.in_([year, year - 1, year + 1]), or_(*token_filters)])

    return candidates[:cap]


def score_fipe_candidate(*, listing_query: dict, catalog_entry) -> dict:
    score = 0
    reasons: list[str] = []
    warnings: list[str] = []

    make_tokens = important_vehicle_tokens(listing_query.get("make"))
    model_tokens = important_vehicle_tokens(listing_query.get("model"))
    version_tokens = important_vehicle_tokens(listing_query.get("version"))
    fuel_tokens = important_vehicle_tokens(listing_query.get("fuel_type"))

    brand_tokens = important_vehicle_tokens(getattr(catalog_entry, "brand_name", None))
    model_name_tokens = important_vehicle_tokens(getattr(catalog_entry, "model_name", None))
    fuel_catalog_tokens = important_vehicle_tokens(getattr(catalog_entry, "fuel", None))

    brand_match = bool(make_tokens and make_tokens.intersection(brand_tokens))
    if brand_match:
        score += 25
        reasons.append("marca compatível")
    elif make_tokens:
        warnings.append("marca divergente")
        score -= 55

    model_overlap = len(model_tokens.intersection(model_name_tokens)) / max(1, len(model_tokens))
    version_overlap = len(version_tokens.intersection(model_name_tokens)) / max(1, len(version_tokens)) if version_tokens else 0
    matched_tokens = sorted(model_tokens.intersection(model_name_tokens) | version_tokens.intersection(model_name_tokens))
    missing_tokens = sorted((model_tokens | version_tokens) - set(matched_tokens))

    if model_overlap > 0:
        score += int(40 * model_overlap)
        reasons.append("modelo compatível")
    else:
        warnings.append("modelo sem interseção relevante")
        score -= 45

    if version_overlap > 0:
        score += int(10 * min(1.0, version_overlap))
        reasons.append("tokens de versão encontrados")

    listing_year = listing_query.get("year")
    model_year = getattr(catalog_entry, "model_year", None)
    year_delta = None
    if listing_year and model_year:
        year_delta = abs(int(listing_year) - int(model_year))
        if year_delta == 0:
            score += 20
            reasons.append("ano compatível")
        elif year_delta == 1:
            score += 8
            warnings.append("ano próximo (diferença de 1 ano)")
        else:
            score -= min(35, 12 * year_delta)
            warnings.append("ano divergente")

    fuel_match = False
    if fuel_tokens and fuel_catalog_tokens:
        fuel_match = bool(fuel_tokens.intersection(fuel_catalog_tokens))
        if fuel_match:
            score += 8
            reasons.append("combustível compatível")
        else:
            warnings.append("combustível divergente")
            score -= 8

    score = max(0, min(100, score))
    label = "high" if score >= 80 else "medium" if score >= 60 else "low"
    return {
        "catalog_entry_id": str(catalog_entry.id),
        "fipe_code": catalog_entry.fipe_code,
        "brand_name": catalog_entry.brand_name,
        "model_name": catalog_entry.model_name,
        "model_year": catalog_entry.model_year,
        "fuel": catalog_entry.fuel,
        "price": float(catalog_entry.price) if catalog_entry.price is not None else None,
        "confidence_score": score,
        "confidence_label": label,
        "reasons": reasons,
        "warnings": warnings,
        "matched_tokens": matched_tokens,
        "missing_tokens": missing_tokens,
        "brand_match": brand_match,
        "model_token_overlap": round(model_overlap, 3),
        "version_token_overlap": round(version_overlap, 3),
        "year_delta": year_delta,
        "fuel_match": fuel_match,
    }


def resolve_listing_to_fipe_candidates(db: Session, *, listing, reference_month: str, limit: int = 10) -> dict:
    month = normalize_fipe_month(reference_month)
    listing_id = str(getattr(listing, "id", ""))
    listing_query = build_listing_fipe_query(listing)
    if not listing_query.get("make") or not listing_query.get("model") or not listing_query.get("year"):
        return {"listing_id": listing_id, "reference_month": month, "query": listing_query, "candidates": [], "best_candidate": None, "status": "insufficient_data"}

    candidates = find_fipe_catalog_candidates(db, listing=listing, reference_month=month, limit=limit)
    scored = sorted((score_fipe_candidate(listing_query=listing_query, catalog_entry=row) for row in candidates), key=lambda x: x["confidence_score"], reverse=True)
    relevant = [c for c in scored if c["confidence_score"] >= 40]

    status = "no_match"
    best = relevant[0] if relevant else None
    ambiguity_reason = None
    if best:
        second = relevant[1] if len(relevant) > 1 else None
        diff = best["confidence_score"] - second["confidence_score"] if second else 100
        if best["confidence_label"] == "high" and second and second["confidence_label"] == "high" and diff < 15:
            status = "ambiguous"
            ambiguity_reason = "segundo candidato também high e próximo"
        elif best["confidence_label"] == "high" and diff >= 15:
            status = "matched"
        elif best["confidence_label"] == "medium":
            status = "ambiguous"
            ambiguity_reason = "melhor candidato com confiança medium"
        else:
            status = "no_match"

    return {"listing_id": listing_id, "reference_month": month, "query": listing_query, "candidates": relevant[:limit], "best_candidate": best, "status": status, "ambiguity_reason": ambiguity_reason}


def build_fipe_resolver_coverage_report(db: Session, *, reference_month: str, limit: int = 100) -> dict:
    month = _ensure_month(db, reference_month)
    sample_limit = max(1, min(200, int(limit)))
    counters = Counter()
    reason_counts = Counter()
    warning_counts = Counter()

    listings = db.query(CarListing).order_by(CarListing.created_at.desc()).limit(sample_limit).all()
    for listing in listings:
        result = resolve_listing_to_fipe_candidates(db, listing=listing, reference_month=month, limit=5)
        status = result["status"]
        counters[status] += 1
        best = result.get("best_candidate")
        if best:
            label = best["confidence_label"]
            counters[f"label_{label}"] += 1
            if status == "matched" and label == "high":
                counters["matched_high"] += 1
            if status == "ambiguous" and label == "high":
                counters["ambiguous_high"] += 1
            if status == "ambiguous" and label == "medium":
                counters["ambiguous_medium"] += 1
            reason_counts.update(best.get("reasons") or [])
            warning_counts.update(best.get("warnings") or [])

    return {
        "reference_month": month,
        "sample_size": len(listings),
        "limit": sample_limit,
        "status_counts": {"matched": counters.get("matched", 0), "ambiguous": counters.get("ambiguous", 0), "no_match": counters.get("no_match", 0), "insufficient_data": counters.get("insufficient_data", 0)},
        "confidence_label_counts": {"high": counters.get("label_high", 0), "medium": counters.get("label_medium", 0), "low": counters.get("label_low", 0)},
        "detailed_counts": {
            "matched_high": counters.get("matched_high", 0),
            "ambiguous_high": counters.get("ambiguous_high", 0),
            "ambiguous_medium": counters.get("ambiguous_medium", 0),
            "no_match": counters.get("no_match", 0),
            "insufficient_data": counters.get("insufficient_data", 0),
        },
        "top_reasons": reason_counts.most_common(5),
        "top_warnings": warning_counts.most_common(5),
    }
