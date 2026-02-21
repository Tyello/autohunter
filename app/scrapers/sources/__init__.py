"""
Scraper Registry - Fase 3: Todos os scrapers.

Auto-registra todos os scrapers implementados.
"""

from __future__ import annotations
from typing import Dict, Optional

from app.scrapers.scraper_base import BaseScraper


# Registry global
_scrapers: Dict[str, BaseScraper] = {}


def register_scraper(scraper: BaseScraper):
    """Registra um scraper."""
    _scrapers[scraper.source] = scraper


def get_scraper(source: str) -> Optional[BaseScraper]:
    """Obtém scraper por nome da fonte."""
    return _scrapers.get(source)


def list_scrapers() -> Dict[str, BaseScraper]:
    """Lista todos os scrapers registrados."""
    return dict(_scrapers)


def has_scraper(source: str) -> bool:
    """Verifica se scraper existe."""
    return source in _scrapers


# Auto-register todos os scrapers
def _auto_register():
    """Auto-registra todos os scrapers implementados."""
    
    # Fase 2: Scrapers piloto
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
    
    # Fase 3: Migração em massa
    try:
        from app.scrapers.sources.olx import OLXScraper
        register_scraper(OLXScraper())
    except ImportError:
        pass
    
    try:
        from app.scrapers.sources.webmotors import WebmotorsScraper
        register_scraper(WebmotorsScraper())
    except ImportError:
        pass
    
    try:
        from app.scrapers.sources.chavesnamao import ChavesNaMaoScraper
        register_scraper(ChavesNaMaoScraper())
    except ImportError:
        pass
    
    try:
        from app.scrapers.sources.kavak import KavakScraper
        register_scraper(KavakScraper())
    except ImportError:
        pass
    
    try:
        from app.scrapers.sources.gogarage_mobiauto import GoGarageScraper, MobiautoScraper
        register_scraper(GoGarageScraper())
        register_scraper(MobiautoScraper())
    except ImportError:
        pass

    try:
        from app.scrapers.sources.turboclass import TurboClassScraper
        register_scraper(TurboClassScraper())
    except ImportError:
        pass


# Auto-register ao importar
_auto_register()
