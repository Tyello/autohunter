"""
BaseScraper - Interface unificada para todos os scrapers.

Todos os scrapers devem herdar desta classe e implementar:
- build_search_url(query, **kwargs) -> str
- parse_listing(raw_data: dict) -> dict | None
- (opcional) extract_raw_data(raw_content: str, ctx) -> list[dict]
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
import time
import traceback

from app.sources.types import ScrapeContext
from app.scrapers.scraper_base.fetcher import unified_fetch
from app.scrapers.scraper_base.metrics import PipelineMetrics
from app.scrapers.base import FetchBlocked
from app.scrapers.shared.circuit_breaker import get_circuit_breaker
from app.scrapers.base import FetchBlocked


@dataclass
class ScraperResult:
    """Resultado padronizado de scraping."""
    
    listings: List[Dict[str, Any]]
    metrics: PipelineMetrics
    warnings: List[str] = field(default_factory=list)
    
    # Diagnósticos
    blocked: bool = False
    partial_failure: bool = False
    
    @property
    def success(self) -> bool:
        """Pipeline teve sucesso se encontrou pelo menos 1 listing válido."""
        return len(self.listings) > 0 and not self.blocked


class BaseScraper(ABC):
    """Interface unificada para todos os scrapers.
    
    Responsabilidades:
    - Define o contrato que todos os scrapers devem seguir
    - Gerencia o pipeline completo (fetch → extract → parse → validate)
    - Integra circuit breaker, metrics e error handling
    - Delega apenas lógica específica da fonte para subclasses
    
    Uso:
        class ICarrosScraper(BaseScraper):
            def __init__(self):
                super().__init__(source_name="icarros")
            
            def build_search_url(self, query: str, **kwargs) -> str:
                return f"https://icarros.com.br/busca?q={query}"
            
            def parse_listing(self, raw_data: dict) -> dict | None:
                return {
                    "external_id": raw_data["id"],
                    "title": raw_data["title"],
                    # ...
                }
    """
    
    def __init__(self, source_name: str):
        """Inicializa scraper.
        
        Args:
            source_name: Nome da fonte (ex: 'icarros', 'olx', etc)
        """
        self.source = source_name
        self._circuit_breaker = get_circuit_breaker(source_name)
    
    @abstractmethod
    def build_search_url(self, query: str, **kwargs) -> str:
        """Constrói URL de busca a partir da query.
        
        Args:
            query: Termo de busca (ex: "civic si")
            **kwargs: Parâmetros opcionais (região, preço, etc)
        
        Returns:
            URL completa de busca
        
        Example:
            >>> scraper.build_search_url("civic si", location="sao-paulo")
            'https://icarros.com.br/busca?q=civic+si&loc=sao-paulo'
        """
        pass
    
    @abstractmethod
    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extrai dados normalizados de um item bruto.
        
        Args:
            raw_data: Dados brutos extraídos (dict do HTML/JSON)
        
        Returns:
            Dicionário normalizado ou None se inválido:
            {
                "external_id": str (obrigatório),
                "title": str,
                "url": str (obrigatório),
                "price": Decimal | None,
                "thumbnail_url": str | None,
                "location": str | None,
                "year": int | None,
                "mileage_km": int | None,
                "make": str | None,
                "model": str | None,
                "extras": dict,  # campos específicos da fonte
                "raw_payload": dict | str | None,  # opcional, para debug
            }
        
        Note:
            - Campos obrigatórios: external_id, url
            - source é injetado automaticamente pelo pipeline
            - Retorne None para itens inválidos (serão ignorados)
        """
        pass
    
    def extract_raw_data(self, raw_content: str, ctx: ScrapeContext) -> List[Dict]:
        """Extrai lista de items brutos do conteúdo (HTML ou JSON).
        
        Implementação default:
        - Tenta parsear como JSON
        - Se falhar, retorna lista vazia (subclasse deve sobrescrever)
        
        Override quando:
        - HTML precisa de parsing específico (BeautifulSoup)
        - JSON tem estrutura não-padrão
        - Precisa de lógica de extração customizada
        
        Args:
            raw_content: HTML ou JSON string
            ctx: Contexto de scraping (configs, flags)
        
        Returns:
            Lista de dicionários com dados brutos
        """
        import json
        
        try:
            data = json.loads(raw_content)
            
            # JSON pode vir em vários formatos
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                # Tenta formatos comuns
                for key in ['items', 'results', 'data', 'listings']:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                # Se não encontrou, retorna o dict como único item
                return [data]
            
            return []
            
        except (json.JSONDecodeError, ValueError):
            # Não é JSON - subclasse deve sobrescrever para HTML
            return []

    def _fetch_content(self, search_url: str, ctx: ScrapeContext):
        """Hook de fetch para customização por source."""
        return unified_fetch(search_url, ctx, source=self.source)
    
    def scrape(self, search_url: str, ctx: ScrapeContext) -> ScraperResult:
        """Pipeline completo: fetch → extract → parse → validate.
        
        Este método NÃO deve ser sobrescrito. Toda customização
        vai em build_search_url, parse_listing ou extract_raw_data.
        
        Args:
            search_url: URL de busca (construída via build_search_url)
            ctx: Contexto com configs da fonte
        
        Returns:
            ScraperResult com listings normalizados, metrics e warnings
        """
        # Inicializa métricas
        metrics = PipelineMetrics(source=self.source)
        metrics.total_started_at = time.time()
        warnings = []
        
        # Check circuit breaker
        if self._circuit_breaker.is_open():
            metrics.circuit_breaker_state = "open"
            metrics.total_duration_ms = int((time.time() - metrics.total_started_at) * 1000)
            
            return ScraperResult(
                listings=[],
                metrics=metrics,
                warnings=["Circuit breaker is open - skipping scrape"],
                blocked=True
            )
        
        try:
            # Stage 1: Fetch
            metrics.fetch_started_at = time.time()
            
            try:
                fetch_result = self._fetch_content(search_url, ctx)
                raw_content = fetch_result.content
                
                metrics.fetch_duration_ms = int((time.time() - metrics.fetch_started_at) * 1000)
                metrics.fetch_method = fetch_result.method
                metrics.fetch_blocked = False
                
            except FetchBlocked as e:
                metrics.fetch_duration_ms = int((time.time() - metrics.fetch_started_at) * 1000)
                metrics.fetch_blocked = True
                metrics.fetch_error = str(e)
                
                self._circuit_breaker.record_failure()
                
                metrics.total_duration_ms = int((time.time() - metrics.total_started_at) * 1000)
                metrics.circuit_breaker_state = self._circuit_breaker.get_state()
                
                return ScraperResult(
                    listings=[],
                    metrics=metrics,
                    warnings=[f"Fetch blocked: {e}"],
                    blocked=True
                )
            
            # Stage 2: Extract
            metrics.extract_started_at = time.time()
            
            try:
                raw_items = self.extract_raw_data(raw_content, ctx)
                metrics.raw_items_found = len(raw_items)
                metrics.extract_duration_ms = int((time.time() - metrics.extract_started_at) * 1000)
                
            except Exception as e:
                metrics.extract_duration_ms = int((time.time() - metrics.extract_started_at) * 1000)
                warnings.append(f"Extract error: {e}")
                raw_items = []
            
            # Stage 3: Parse
            metrics.parse_started_at = time.time()
            
            listings = []
            parse_errors = 0
            
            for idx, item in enumerate(raw_items):
                try:
                    parsed = self.parse_listing(item)
                    
                    if parsed is None:
                        warnings.append(f"Item {idx}: parse_listing returned None")
                        continue
                    
                    # Validação mínima
                    if not parsed.get("external_id"):
                        warnings.append(f"Item {idx}: missing external_id")
                        metrics.items_invalid += 1
                        continue
                    
                    if not parsed.get("url"):
                        warnings.append(f"Item {idx}: missing url")
                        metrics.items_invalid += 1
                        continue
                    
                    # Inject source
                    parsed["source"] = self.source
                    
                    listings.append(parsed)
                    metrics.items_valid += 1
                    
                except Exception as e:
                    parse_errors += 1
                    warnings.append(f"Item {idx}: parse error - {e}")
            
            metrics.items_parsed = len(listings)
            metrics.parse_errors = parse_errors
            metrics.parse_duration_ms = int((time.time() - metrics.parse_started_at) * 1000)
            
            # Success - record no circuit breaker
            self._circuit_breaker.record_success()
            metrics.circuit_breaker_state = "closed"
            
            metrics.total_duration_ms = int((time.time() - metrics.total_started_at) * 1000)
            
            return ScraperResult(
                listings=listings,
                metrics=metrics,
                warnings=warnings,
                blocked=False,
                partial_failure=(parse_errors > 0 or len(warnings) > 0)
            )
            
        except Exception as e:
            # Unexpected error - record failure
            self._circuit_breaker.record_failure()
            
            metrics.total_duration_ms = int((time.time() - metrics.total_started_at) * 1000)
            metrics.circuit_breaker_state = self._circuit_breaker.get_state()
            
            # Re-raise com contexto
            raise RuntimeError(
                f"Scraper {self.source} failed: {e}\n"
                f"Traceback:\n{traceback.format_exc()}"
            ) from e
