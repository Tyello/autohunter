from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.car_listings_repo import insert_ignore_duplicates_return_ids


# car_listings.price is NUMERIC(12,2): absolute value must be < 10^10.
_MAX_DB_PRICE = Decimal("9999999999.99")


@dataclass(frozen=True)
class IngestStats:
    """Estatísticas de ingest.

    inserted_new / updated dependem de o repo suportar `with_stats=True`.
    Em versões antigas, caímos para uma estimativa compatível.
    """
    ids: list
    inserted_new: int
    updated: int
    upserted: int


def _sanitize_price(v: Any) -> Decimal | None:
    """Hard guard to prevent DB numeric overflows.

    Scrapers are best-effort; if they mis-parse a long digit sequence, we must
    not allow a single bad listing to kill the whole bulk upsert.
    """
    if v is None:
        return None

    try:
        if isinstance(v, Decimal):
            d = v
        elif isinstance(v, (int, float)):
            d = Decimal(str(v))
        elif isinstance(v, str):
            vv = v.strip()
            if not vv:
                return None
            vv = "".join(ch for ch in vv if ch.isdigit() or ch in ".,")
            vv = vv.replace(".", "").replace(",", ".")
            d = Decimal(vv)
        else:
            return None
    except (InvalidOperation, ValueError):
        return None

    if not d.is_finite() or d <= 0 or d > _MAX_DB_PRICE:
        return None
    try:
        return d.quantize(Decimal("0.01"))
    except Exception:
        return d


def _sanitize_listing(listing: dict) -> dict:
    sanitized = dict(listing)
    if "price" in sanitized:
        sanitized["price"] = _sanitize_price(sanitized.get("price"))
    return sanitized


def _sanitize_listings(listings: list[dict]) -> list[dict]:
    out: list[dict] = []
    for listing in listings or []:
        if not isinstance(listing, dict):
            continue
        out.append(_sanitize_listing(listing))
    return out


def ingest_listings(db: Session, listings: list[dict]):
    """Compat: retorna lista de IDs upsertados."""
    if not listings:
        return []

    listings = _sanitize_listings(listings)
    inserted_ids = insert_ignore_duplicates_return_ids(db, listings)
    return list(inserted_ids or [])


def ingest_listings_stats(db: Session, listings: list[dict]) -> IngestStats:
    """Ingest com contagem separada: novos vs updates.

    - Se `insert_ignore_duplicates_return_ids(..., with_stats=True)` existir,
      usamos os contadores reais.
    - Caso contrário (repo antigo), mantemos compatibilidade sem quebrar o scheduler.
    """
    if not listings:
        return IngestStats(ids=[], inserted_new=0, updated=0, upserted=0)

    listings = _sanitize_listings(listings)

    try:
        res = insert_ignore_duplicates_return_ids(db, listings, with_stats=True)
        if isinstance(res, dict):
            ids = list(res.get("ids") or [])
            inserted_new = int(res.get("inserted_new") or 0)
            updated = int(res.get("updated") or 0)
            upserted = int(res.get("upserted") or 0)
            return IngestStats(ids=ids, inserted_new=inserted_new, updated=updated, upserted=upserted)

        # fallback defensive: if a future repo returns a list even with with_stats
        ids = list(res or [])
        return IngestStats(ids=ids, inserted_new=len(ids), updated=0, upserted=len(ids))

    except TypeError:
        # Repo não suporta with_stats -> comportamento antigo
        ids = list(insert_ignore_duplicates_return_ids(db, listings) or [])
        return IngestStats(ids=ids, inserted_new=len(ids), updated=0, upserted=len(ids))
