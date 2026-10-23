"""Resposta imediata para wishlist recem-criada, sem tocar a rede.

O estoque de anuncios ja ingerido pelas outras buscas costuma conter candidatos para a busca
nova. Casamos esse estoque na hora e enfileiramos as notificacoes (dedupe por wishlist+anuncio),
entao o usuario recebe algo em segundos e a varredura da source vira so complemento.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Collection

from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.wishlist import Wishlist
from app.services.matching_service import match_listings_for_wishlists
from app.services.notifications_queue_service import queue_notifications_for_matches_diag

logger = logging.getLogger(__name__)

# Teto de anuncios lidos do estoque por criacao (protege a RAM do Raspberry).
_STOCK_SCAN_LIMIT = 500


def backfill_wishlist_from_stock(
    db: Session,
    wishlist: Wishlist,
    *,
    sources: Collection[str],
    hours: int,
    max_notifications: int,
) -> dict[str, Any]:
    """Casa o estoque recente das `sources` com a wishlist e enfileira ate `max_notifications`.

    Nao faz commit (quem chama decide) e nunca levanta: falha aqui nao pode impedir a criacao.
    """
    out: dict[str, Any] = {"considered": 0, "matched": 0, "queued": 0, "cap_skipped": 0}
    wanted = {str(s).strip().lower() for s in (sources or []) if s}
    if not wanted or int(max_notifications or 0) <= 0 or int(hours or 0) <= 0:
        return out

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=int(hours))
        listings = (
            db.query(CarListing)
            .filter(CarListing.source.in_(wanted))
            .filter(CarListing.is_sold.is_(False))
            .filter(CarListing.status != "inativo")
            .filter(CarListing.last_seen_at >= cutoff)
            .order_by(CarListing.last_seen_at.desc())
            .limit(_STOCK_SCAN_LIMIT)
            .all()
        )
        out["considered"] = len(listings)
        if not listings:
            return out

        matched = (match_listings_for_wishlists([wishlist], listings) or {}).get(wishlist.id) or []
        out["matched"] = len(matched)
        if not matched:
            return out

        diag = queue_notifications_for_matches_diag(db, wishlist, matched, max_queue=int(max_notifications))
        out["queued"] = int(diag.get("queued") or 0)
        out["cap_skipped"] = int(diag.get("cap_skipped") or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("initial backfill failed wishlist_id=%s err=%s", getattr(wishlist, "id", None), exc)
        out["error"] = type(exc).__name__
    return out
