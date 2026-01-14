from typing import List, Dict, Any
from sqlalchemy.orm import Session
from urllib.parse import quote_plus

from app.services.listings_service import ingest_listings
from app.models.car_listing import CarListing

from app.scrapers.mercadolivre import scrape_mercadolivre
from app.scrapers.olx import scrape_olx
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
    """
    Faz scraping leve nas duas fontes, persiste no DB (com dedupe) e retorna
    anúncios recentes para responder no bot.
    """
    ml_url = build_ml_search_url(query)
    olx_url = build_olx_search_url(query)

    ml_items = scrape_mercadolivre(ml_url)
    olx_items = []
    try:
        olx_items = scrape_olx(olx_url)
    except FetchBlocked:
        # MVP: ignora OLX por enquanto
        olx_items = []
    except Exception:
        olx_items = []

    # ingest: retorna IDs novos, mas para busca manual também queremos "top resultados"
    # Aqui persistimos tudo (dedupe) e depois buscamos no DB os mais recentes dessas fontes.
    ingest_listings(db, ml_items)
    ingest_listings(db, olx_items)

    # Retorno simples: últimos anúncios inseridos/atualizados não é trivial sem update,
    # então retornamos os mais recentes por created_at filtrando pelas fontes.
    rows = (
        db.query(CarListing)
        .filter(CarListing.source.in_(["mercadolivre", "olx"]))
        .order_by(CarListing.created_at.desc())
        .limit(limit)
        .all()
    )
    return rows
