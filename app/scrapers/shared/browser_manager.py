"""
Browser Manager - Singleton para gerenciar Playwright pool.

Otimizado para Raspberry Pi 4:
- 1 browser global (Chromium)
- Reutilização de contextos por (source, proxy)
- Eviction de contextos idle (TTL-based)
- Resource blocking (imagens, fonts) para economizar RAM/CPU
- Single-process mode para minimizar overhead
"""

from __future__ import annotations
import os
import time
import threading
from typing import Optional, Dict, Tuple
from dataclasses import dataclass


@dataclass
class BrowserFetchResult:
    """Resultado de fetch via browser."""
    
    html: str
    final_url: str
    method: str = "browser"


class BrowserManager:
    """Singleton para gerenciar Playwright pool.
    
    Características:
    - Lazy initialization (só inicia quando primeiro fetch é solicitado)
    - 1 browser global (economia de RAM)
    - Pool de contextos reutilizáveis (max 5)
    - TTL-based eviction (5min idle)
    - Resource blocking configurável
    - Thread-safe
    
    Otimizações Raspberry Pi 4:
    - --single-process (crítico para economizar RAM)
    - Desabilitar features desnecessárias
    - Block imagens/fonts por padrão
    - Limitar contextos simultâneos
    
    Example:
        mgr = get_browser_manager()
        result = mgr.fetch_html(
            url="https://example.com",
            source="olx",
            timeout_ms=30000
        )
        print(result.html)
    """
    
    _instance: Optional['BrowserManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Inicializa (uma vez)."""
        if getattr(self, '_initialized', False):
            return
        
        self._initialized = True
        self._browser = None
        self._playwright = None
        
        # Pool de contextos: (source, proxy_key) -> context
        self._contexts: Dict[Tuple[str, str], Any] = {}
        self._context_last_used: Dict[Tuple[str, str], float] = {}
        
        # Configurações
        self._max_contexts = int(os.getenv('PLAYWRIGHT_MAX_CONTEXTS', '5'))
        self._context_ttl_s = int(os.getenv('PLAYWRIGHT_CONTEXT_TTL_SECONDS', '300'))  # 5min
        
        self._startup_lock = threading.Lock()
        self._context_lock = threading.Lock()
    
    def start(self):
        """Lazy init: só inicia quando primeiro fetch browser é solicitado.
        
        Thread-safe.
        """
        if self._browser is not None:
            return
        
        with self._startup_lock:
            if self._browser is not None:
                return
            
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as e:
                raise RuntimeError(
                    "Playwright not installed. Run:\n"
                    "  pip install playwright\n"
                    "  python -m playwright install chromium"
                ) from e
            
            self._playwright = sync_playwright().start()
            
            # Configurações otimizadas para Raspberry Pi
            browser_args = [
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-gpu',
                '--disable-software-rasterizer',
                '--single-process',  # CRÍTICO: economiza ~200MB RAM
                '--disable-background-networking',
                '--disable-default-apps',
                '--disable-sync',
                '--disable-translate',
                '--hide-scrollbars',
                '--metrics-recording-only',
                '--mute-audio',
                '--no-first-run',
                '--safebrowsing-disable-auto-update',
            ]
            
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=browser_args
            )
    
    def fetch_html(
        self,
        url: str,
        source: str,
        proxy: Optional[str] = None,
        timeout_ms: int = 30000,
        wait_until: str = "domcontentloaded",
        block_resources: bool = True
    ) -> BrowserFetchResult:
        """Fetch com context pool.
        
        Args:
            url: URL para fetch
            source: Nome da fonte (para pool key)
            proxy: Proxy URL (opcional)
            timeout_ms: Timeout em milissegundos
            wait_until: Critério de wait ('load'|'domcontentloaded'|'networkidle')
            block_resources: Bloquear imagens/fonts (economia RAM/CPU)
        
        Returns:
            BrowserFetchResult com HTML e final URL
        
        Raises:
            TimeoutError: Se timeout
            Exception: Outros erros de navegação
        """
        self.start()
        
        context = self._get_or_create_context(source, proxy)
        page = context.new_page()
        
        try:
            # Setup resource blocking
            if block_resources:
                self._setup_resource_blocking(page, source)
            
            # Navigate
            response = page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            
            # Wait a bit extra for dynamic content (opcional)
            # page.wait_for_timeout(500)
            
            html = page.content()
            final_url = page.url
            
            return BrowserFetchResult(html=html, final_url=final_url)
            
        finally:
            # Sempre fechar page
            try:
                page.close()
            except:
                pass
            
            # Atualizar last_used
            self._touch_context(source, proxy)
    
    def _get_or_create_context(self, source: str, proxy: Optional[str]):
        """Obtém context do pool ou cria novo.
        
        Thread-safe, com eviction de idle contexts.
        """
        proxy_key = proxy or "__default__"
        key = (source, proxy_key)
        
        with self._context_lock:
            # Evict idle contexts se pool cheio
            if len(self._contexts) >= self._max_contexts:
                self._evict_idle_contexts()
            
            # Retorna se já existe
            if key in self._contexts:
                return self._contexts[key]
            
            # Cria novo context
            ctx_kwargs = {
                "user_agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "viewport": {"width": 1280, "height": 720},
                "locale": "pt-BR",
                "timezone_id": "America/Sao_Paulo",
            }
            
            if proxy:
                ctx_kwargs["proxy"] = {"server": proxy}
            
            context = self._browser.new_context(**ctx_kwargs)
            self._contexts[key] = context
            self._context_last_used[key] = time.time()
            
            return context
    
    def _setup_resource_blocking(self, page, source: str):
        """Block imagens/fonts/media para economizar RAM/CPU.
        
        Exceções: fontes que precisam de recursos para anti-bot.
        """
        # Whitelist: fontes que NÃO devem bloquear recursos
        # (alguns anti-bot detectam quando recursos não são carregados)
        no_block_sources = {
            "mobiauto",
            "facebook_marketplace",
            "icarros"  # algumas imagens têm dados no nome
        }
        
        if source in no_block_sources:
            return
        
        def route_handler(route):
            """Handler para bloquear recursos pesados."""
            resource_type = route.request.resource_type
            
            # Block: images, media, fonts, stylesheets
            if resource_type in ("image", "media", "font", "stylesheet"):
                route.abort()
            else:
                route.continue_()
        
        try:
            page.route("**/*", route_handler)
        except:
            # Se route() não suportado, ignore
            pass
    
    def _touch_context(self, source: str, proxy: Optional[str]):
        """Atualiza timestamp de último uso."""
        proxy_key = proxy or "__default__"
        key = (source, proxy_key)
        
        with self._context_lock:
            self._context_last_used[key] = time.time()
    
    def _evict_idle_contexts(self):
        """Remove contextos idle (LRU + TTL).
        
        Estratégia:
        1. Remove todos os contextos idle por > TTL
        2. Se ainda cheio, remove o mais antigo (LRU)
        """
        now = time.time()
        
        # 1. Remove por TTL
        to_remove = []
        for key, last_used in list(self._context_last_used.items()):
            if (now - last_used) > self._context_ttl_s:
                to_remove.append(key)
        
        for key in to_remove:
            self._close_context(key)
        
        # 2. Se ainda cheio, remove LRU
        if len(self._contexts) >= self._max_contexts:
            if self._context_last_used:
                oldest_key = min(self._context_last_used, key=self._context_last_used.get)
                self._close_context(oldest_key)
    
    def _close_context(self, key: Tuple[str, str]):
        """Fecha e remove context do pool."""
        ctx = self._contexts.pop(key, None)
        if ctx:
            try:
                ctx.close()
            except:
                pass
        
        self._context_last_used.pop(key, None)
    
    def get_stats(self) -> dict:
        """Retorna estatísticas do pool."""
        with self._context_lock:
            return {
                "started": self._browser is not None,
                "contexts": len(self._contexts),
                "max_contexts": self._max_contexts,
                "context_ttl_s": self._context_ttl_s,
                "context_keys": [f"{src}::{proxy}" for src, proxy in self._contexts.keys()],
            }
    
    def shutdown(self):
        """Graceful shutdown (fecha tudo).
        
        Use em cleanup/exit handlers.
        """
        with self._context_lock:
            # Fecha todos os contexts
            for ctx in list(self._contexts.values()):
                try:
                    ctx.close()
                except:
                    pass
            self._contexts.clear()
            self._context_last_used.clear()
        
        with self._startup_lock:
            # Fecha browser
            if self._browser:
                try:
                    self._browser.close()
                except:
                    pass
                self._browser = None
            
            # Fecha playwright
            if self._playwright:
                try:
                    self._playwright.stop()
                except:
                    pass
                self._playwright = None


# Singleton global
_browser_manager: Optional[BrowserManager] = None


def get_browser_manager() -> BrowserManager:
    """Retorna singleton do BrowserManager.
    
    Lazy init - só cria na primeira chamada.
    """
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager


def shutdown_browser_manager():
    """Shutdown do browser manager (para cleanup)."""
    global _browser_manager
    if _browser_manager is not None:
        _browser_manager.shutdown()
        _browser_manager = None
