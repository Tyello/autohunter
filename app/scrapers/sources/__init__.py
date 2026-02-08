"""
Scraper Registry - Gerencia todos os scrapers disponíveis.

Centraliza instanciação e lookup de scrapers.
"""

from __future__ import annotations
from typing import Dict, Optional

from app.scrapers.scraper_base import BaseScraper


# Registry global
_scrapers: Dict[str, BaseScraper] = {}


def register_scraper(scraper: BaseScraper):
    """Registra um scraper.
    
    Args:
        scraper: Instância do scraper
    """
    _scrapers[scraper.source] = scraper


def get_scraper(source: str) -> Optional[BaseScraper]:
    """Obtém scraper por nome da fonte.
    
    Args:
        source: Nome da fonte (ex: "icarros")
    
    Returns:
        BaseScraper ou None se não encontrado
    """
    return _scrapers.get(source)


def list_scrapers() -> Dict[str, BaseScraper]:
    """Lista todos os scrapers registrados."""
    return dict(_scrapers)


def has_scraper(source: str) -> bool:
    """Verifica se scraper existe."""
    return source in _scrapers


# Auto-register scrapers disponíveis
def _auto_register():
    """Auto-registra todos os scrapers implementados."""
    try:
        from app.scrapers.sources.icarros import ICarrosScraper
        register_scraper(ICarrosScraper())
    except ImportError:
        pass
    
    try:
        from app.scrapers.sources.mercadolivre import MercadoLivreScraper
        register_scraper(MercadoLivreScraper())
    except ImportError:
        pass


# Auto-register ao importar
_auto_register()
