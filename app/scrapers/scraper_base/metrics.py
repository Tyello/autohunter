"""
PipelineMetrics - Métricas estruturadas do pipeline de scraping.

Coleta métricas de cada stage (fetch, extract, parse, validate)
para observabilidade e debugging.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class PipelineMetrics:
    """Métricas de execução do pipeline de scraping.
    
    Organizado por stages:
    - Fetch: tempo, método (http/browser), bloqueios
    - Extract: tempo, itens encontrados
    - Parse: tempo, itens parseados, erros
    - Validate: itens válidos vs inválidos
    - Circuit Breaker: estado atual
    - Total: tempo total do pipeline
    """
    
    source: str
    
    # Fetch stage
    fetch_started_at: float = 0
    fetch_duration_ms: int = 0
    fetch_method: str = "unknown"  # http | browser | hybrid
    fetch_blocked: bool = False
    fetch_error: Optional[str] = None
    
    # Extract stage
    extract_started_at: float = 0
    extract_duration_ms: int = 0
    raw_items_found: int = 0
    
    # Parse stage
    parse_started_at: float = 0
    parse_duration_ms: int = 0
    items_parsed: int = 0
    parse_errors: int = 0
    
    # Validate stage
    items_valid: int = 0
    items_invalid: int = 0
    
    # Circuit Breaker
    circuit_breaker_state: str = "unknown"  # closed | open | half_open
    
    # Total
    total_started_at: float = 0
    total_duration_ms: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dict para logging/telemetry."""
        return {
            "source": self.source,
            "fetch": {
                "duration_ms": self.fetch_duration_ms,
                "method": self.fetch_method,
                "blocked": self.fetch_blocked,
                "error": self.fetch_error,
            },
            "extract": {
                "duration_ms": self.extract_duration_ms,
                "raw_items": self.raw_items_found,
            },
            "parse": {
                "duration_ms": self.parse_duration_ms,
                "parsed": self.items_parsed,
                "errors": self.parse_errors,
            },
            "validate": {
                "valid": self.items_valid,
                "invalid": self.items_invalid,
            },
            "circuit_breaker": {
                "state": self.circuit_breaker_state,
            },
            "total": {
                "duration_ms": self.total_duration_ms,
            }
        }
    
    @property
    def success_rate(self) -> float:
        """Taxa de sucesso (itens válidos / itens encontrados)."""
        if self.raw_items_found == 0:
            return 0.0
        return self.items_valid / self.raw_items_found
    
    @property
    def parse_error_rate(self) -> float:
        """Taxa de erros de parsing."""
        if self.raw_items_found == 0:
            return 0.0
        return self.parse_errors / self.raw_items_found
    
    def __str__(self) -> str:
        """Representação resumida."""
        return (
            f"PipelineMetrics({self.source}): "
            f"{self.items_valid}/{self.raw_items_found} valid, "
            f"{self.fetch_method}, "
            f"{self.total_duration_ms}ms, "
            f"cb={self.circuit_breaker_state}"
        )
