"""
Unified Fetcher - Estratégia unificada de fetch (HTTP vs Browser).

Gerencia a decisão de quando usar HTTP simples vs Playwright browser
baseado nas configurações do ScrapeContext.
"""

from __future__ import annotations
import time
from typing import Optional
from dataclasses import dataclass

from app.sources.types import ScrapeContext
from app.scrapers.base import fetch_html, FetchBlocked


@dataclass
class FetchResult:
    """Resultado de fetch com metadados."""
    
    content: str
    final_url: str
    method: str  # "http" | "browser" | "hybrid"
    duration_ms: int
    blocked: bool = False


def unified_fetch(url: str, ctx: ScrapeContext, source: str) -> FetchResult:
    """Estratégia unificada de fetch.
    
    Fluxo de decisão:
    1. force_browser=True → vai direto para browser
    2. fetch_mode="browser" → browser obrigatório
    3. fetch_mode="http" + browser_fallback_enabled → tenta HTTP, fallback browser
    4. fetch_mode="http" (default) → HTTP only
    
    Args:
        url: URL para fazer fetch
        ctx: Contexto de scraping com configurações
        source: Nome da fonte (para logging/pool)
    
    Returns:
        FetchResult com conteúdo e metadados
    
    Raises:
        FetchBlocked: Quando fetch é bloqueado e não há fallback
    """
    start = time.time()
    
    # Força browser (ignorar HTTP)
    if ctx.force_browser:
        content, final_url = _fetch_browser(url, ctx, source)
        return FetchResult(
            content=content,
            final_url=final_url,
            method="browser",
            duration_ms=int((time.time() - start) * 1000),
            blocked=False
        )
    
    # Browser obrigatório (por fetch_mode)
    fetch_mode = getattr(ctx, 'fetch_mode', 'http')
    if fetch_mode == 'browser':
        content, final_url = _fetch_browser(url, ctx, source)
        return FetchResult(
            content=content,
            final_url=final_url,
            method="browser",
            duration_ms=int((time.time() - start) * 1000),
            blocked=False
        )
    
    # Tenta HTTP primeiro
    try:
        content = fetch_html(url, ctx=ctx)
        
        return FetchResult(
            content=content,
            final_url=url,  # fetch_html não retorna final_url
            method="http",
            duration_ms=int((time.time() - start) * 1000),
            blocked=False
        )
        
    except FetchBlocked as e:
        # HTTP bloqueado - tenta fallback se habilitado
        if ctx.browser_fallback_enabled:
            try:
                content, final_url = _fetch_browser(url, ctx, source)
                return FetchResult(
                    content=content,
                    final_url=final_url,
                    method="hybrid",  # indica que HTTP falhou, browser funcionou
                    duration_ms=int((time.time() - start) * 1000),
                    blocked=False
                )
            except Exception as browser_error:
                # Browser também falhou - re-raise original FetchBlocked
                raise e
        
        # Sem fallback - re-raise
        raise e


def _fetch_browser(url: str, ctx: ScrapeContext, source: str) -> tuple[str, str]:
    """Fetch via Playwright (pool gerenciado).
    
    Args:
        url: URL para fetch
        ctx: Contexto com timeouts e configs
        source: Nome da fonte
    
    Returns:
        (content, final_url)
    
    Raises:
        Exception: Se browser fetch falhar
    """
    from app.scrapers.shared.browser_manager import get_browser_manager
    
    browser_mgr = get_browser_manager()
    
    # Timeout do contexto ou default 30s
    timeout_ms = ctx.browser_timeout_ms or 30000
    wait_until = ctx.browser_wait_until or "domcontentloaded"
    
    # Block recursos por padrão (economia de RAM/CPU)
    # Exceto para fontes que precisam de recursos para anti-bot
    block_resources = True
    
    result = browser_mgr.fetch_html(
        url=url,
        source=source,
        proxy=ctx.proxy_server,
        timeout_ms=timeout_ms,
        wait_until=wait_until,
        block_resources=block_resources
    )
    
    return result.html, result.final_url
