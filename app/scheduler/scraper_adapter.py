"""
Scheduler Adapter - Integra novos scrapers (BaseScraper) no scheduler existente.

Este módulo permite usar tanto scrapers legacy quanto novos sem breaking changes.
"""

from __future__ import annotations
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.sources.types import ScrapeContext
from app.scrapers.sources import get_scraper, has_scraper
from app.services.source_configs_service import get_source_config


def should_use_new_scraper(source: str) -> bool:
    """Decide se deve usar novo scraper (BaseScraper) ou legacy.
    
    Estratégia:
    1. Verifica feature flag global USE_NEW_SCRAPERS
    2. Verifica feature flag específico USE_NEW_SCRAPER_{source}
    3. Verifica se scraper novo existe
    
    Args:
        source: Nome da fonte
    
    Returns:
        True se deve usar novo scraper
    """
    # Feature flag global
    use_new = settings.use_new_scrapers
    if not use_new:
        return False
    
    # Feature flag específico (override)
    source_flag = settings.should_use_new_scraper_for(source)

    if source_flag is not None:
        return source_flag

    # Se não tem flag específico, usa global + verifica existência
    return has_scraper(source)


def build_scrape_context(db: Session, source: str) -> Optional[ScrapeContext]:
    """Constrói ScrapeContext a partir do source_configs no DB.
    
    Args:
        db: Sessão do DB
        source: Nome da fonte
    
    Returns:
        ScrapeContext ou None se config não existe
    """
    config = get_source_config(db, source)
    if not config or not config.is_enabled:
        return None
    
    # Extra fields (JSONB)
    extra = config.extra or {}
    
    # Constrói contexto
    ctx = ScrapeContext(
        source=source,
        proxy_server=config.proxy_server,
        browser_fallback_enabled=config.browser_fallback_enabled,
        force_browser=config.force_browser,
        
        # HTTP tunables
        http_connect_timeout_s=extra.get("http_connect_timeout_s"),
        http_read_timeout_s=extra.get("http_read_timeout_s"),
        http_timeout_s=extra.get("http_timeout_s"),
        http_min_delay_ms=extra.get("http_min_delay_ms"),
        http_max_delay_ms=extra.get("http_max_delay_ms"),
        
        # Browser tunables
        browser_timeout_ms=extra.get("browser_timeout_ms"),
        browser_wait_until=extra.get("browser_wait_until"),
        browser_min_delay_ms=extra.get("browser_min_delay_ms"),
        browser_max_delay_ms=extra.get("browser_max_delay_ms"),
        
        # Extra
        extra=extra,
    )
    
    return ctx


def scrape_with_new_scraper(
    db: Session,
    source: str,
    query: str
) -> Dict[str, Any]:
    """Executa scraping usando novo scraper (BaseScraper).
    
    Args:
        db: Sessão do DB
        source: Nome da fonte
        query: Query de busca
    
    Returns:
        Dict com resultado:
        {
            "ok": bool,
            "listings": list,
            "metrics": dict,
            "warnings": list,
            "blocked": bool,
        }
    """
    # Get scraper
    scraper = get_scraper(source)
    if not scraper:
        return {
            "ok": False,
            "reason": "scraper_not_found",
            "listings": [],
        }
    
    # Build context
    ctx = build_scrape_context(db, source)
    if not ctx:
        return {
            "ok": False,
            "reason": "source_disabled_or_not_configured",
            "listings": [],
        }
    
    # Build search URL
    try:
        search_url = scraper.build_search_url(query)
    except Exception as e:
        return {
            "ok": False,
            "reason": "build_url_failed",
            "error": str(e),
            "listings": [],
        }
    
    # Scrape
    try:
        result = scraper.scrape(search_url, ctx)
        
        return {
            "ok": result.success,
            "listings": result.listings,
            "metrics": result.metrics.to_dict(),
            "warnings": result.warnings,
            "blocked": result.blocked,
            "partial_failure": result.partial_failure,
        }
        
    except Exception as e:
        return {
            "ok": False,
            "reason": "scrape_exception",
            "error": str(e),
            "listings": [],
        }


def scrape_source_smart(
    db: Session,
    source: str,
    query: str,
    use_legacy_fallback: bool = True
) -> Dict[str, Any]:
    """Scraping inteligente: tenta novo scraper, fallback para legacy.
    
    Args:
        db: Sessão do DB
        source: Nome da fonte
        query: Query de busca
        use_legacy_fallback: Se True, usa legacy se novo falhar
    
    Returns:
        Dict com resultado + campo "method" indicando qual foi usado
    """
    # Tenta novo scraper se habilitado
    if should_use_new_scraper(source):
        result = scrape_with_new_scraper(db, source, query)
        result["method"] = "new_scraper"
        
        # Se sucesso, retorna
        if result.get("ok"):
            return result
        
        # Se falhou e não tem fallback, retorna erro
        if not use_legacy_fallback:
            return result
        
        # Log: tentando fallback
        result["method"] = "new_scraper_failed_fallback_legacy"
    
    # Fallback para legacy (não implementado aqui)
    # O scheduler existente continua funcionando
    return {
        "ok": False,
        "reason": "legacy_scraper_not_implemented_in_adapter",
        "method": "legacy",
        "listings": [],
    }
