from typing import List
from sqlalchemy.orm import Session
from urllib.parse import quote_plus

from app.core.settings import settings

from app.services.system_logs_service import log
from app.services.source_availability_service import is_in_cooldown
from app.services.listings_service import ingest_listings

from app.models.car_listing import CarListing

from app.scrapers.mercadolivre import scrape_mercadolivre
from app.scrapers.olx import scrape_olx, build_olx_search_url
from app.scrapers.base import FetchBlocked


def build_ml_search_url(query: str) -> str:
    # MVP: URL simples de busca do ML
    # Ex: https://lista.mercadolivre.com.br/<query>
    q = quote_plus(query.strip())
    return f"https://lista.mercadolivre.com.br/{q}"


def build_olx_search_url(query: str) -> str:
    # MVP: URL simples (pode variar por região; mantém genérico)
    q = quote_plus(query.strip())
    return f"https://www.olx.com.br/brasil?q={q}"


def manual_search(db: Session, query: str, limit: int = 5) -> List[CarListing]:
    ml_url = build_ml_search_url(query)
    olx_url = build_olx_search_url(query)

    # ML
    ml_items = scrape_mercadolivre(ml_url)
    ingest_listings(db, ml_items)

    # OLX (best-effort)
    if settings.enable_olx and not is_in_cooldown(db, "olx", settings.olx_cooldown_minutes):
        try:
            olx_items = scrape_olx(olx_url)
            ingest_listings(db, olx_items)
        except FetchBlocked as e:
            log(db, "warning", "scraper_olx", "source_blocked", {"status_code": e.status_code, "url": e.url})
        except Exception as e:
            log(db, "error", "scraper_olx", "scrape_failed", {"error": str(e), "url": olx_url})

    terms = [t for t in query.lower().split() if t]

    q = db.query(CarListing)

    # opcional: só coisas recentes (evita lixo antigo na busca manual)
    # q = q.filter(CarListing.created_at >= datetime.now(timezone.utc) - timedelta(hours=24))

    # match simples: todos os termos no título/location
    for t in terms:
        q = q.filter(
            (CarListing.title.ilike(f"%{t}%")) |
            (CarListing.location.ilike(f"%{t}%"))
        )

    return q.order_by(CarListing.created_at.desc()).limit(limit).all()


def _olx_items_to_listings(items):
    listings = []
    for it in items:
        listings.append({
            "source": "olx",
            "external_id": str(it.external_id),
            "title": it.title or "",
            "url": it.url,
            "thumbnail_url": it.thumbnail_url,
            "price": it.price,          # Decimal ou None
            "currency": "BRL",
            "location": it.location,
        })
    return listings