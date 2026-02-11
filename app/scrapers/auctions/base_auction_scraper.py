"""
Base Scraper para Leilões.

Classe base para scrapers de sites de leilão.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime
from decimal import Decimal

from bs4 import BeautifulSoup

from app.scrapers.scraper_base import BaseScraper


class BaseAuctionScraper(BaseScraper):
    """Base class para scrapers de leilão.
    
    Extende BaseScraper com funcionalidades específicas para leilões.
    """
    
    def __init__(self, source_name: str):
        super().__init__(source_name=source_name)
    
    # ========== Abstract Methods (Subclasses MUST implement) ==========
    
    @abstractmethod
    def extract_events(self, raw_content: str, ctx) -> List[Dict[str, Any]]:
        """Extrai lista de eventos/sessões de leilão.
        
        Args:
            raw_content: HTML ou JSON do site
            ctx: ScrapeContext
        
        Returns:
            Lista de dicts com dados brutos de eventos
        """
        pass
    
    @abstractmethod
    def parse_event(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normaliza dados de um evento.
        
        Args:
            raw_data: Dict com dados brutos do evento
        
        Returns:
            Dict normalizado ou None se inválido
        """
        pass
    
    @abstractmethod
    def extract_lots(self, raw_content: str, ctx, event_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Extrai lista de lotes.
        
        Args:
            raw_content: HTML ou JSON do site
            ctx: ScrapeContext
            event_id: ID do evento (se aplicável)
        
        Returns:
            Lista de dicts com dados brutos de lotes
        """
        pass
    
    @abstractmethod
    def parse_lot(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normaliza dados de um lote.
        
        Args:
            raw_data: Dict com dados brutos do lote
        
        Returns:
            Dict normalizado ou None se inválido
        """
        pass
    
    # ========== Helper Methods (Shared Utilities) ==========
    
    def _parse_bid_value(self, s: str) -> Optional[Decimal]:
        """Parse valor de lance."""
        if not s:
            return None
        
        import re
        
        # Remove símbolos
        s = s.replace("R$", "").replace("$", "").strip()
        s = s.replace(".", "").replace(",", ".")
        s = re.sub(r'[^\d.]', '', s)
        
        if not s:
            return None
        
        try:
            return Decimal(s)
        except:
            return None
    
    def _parse_datetime(self, s: str) -> Optional[datetime]:
        """Parse data/hora (vários formatos)."""
        if not s:
            return None
        
        import re
        from dateutil import parser
        
        try:
            # Remove timezone info se houver
            s = re.sub(r'\([^)]+\)', '', s).strip()
            
            # Tenta parser padrão
            dt = parser.parse(s, dayfirst=True)
            return dt
        except:
            return None
    
    def _normalize_status(self, s: str) -> str:
        """Normaliza status do lote/evento.
        
        Returns:
            scheduled | live | sold | unsold | ended | cancelled
        """
        if not s:
            return "scheduled"
        
        s = s.lower()
        
        # Lote vendido
        if any(x in s for x in ["vendido", "sold", "arrematado"]):
            return "sold"
        
        # Lote não vendido
        if any(x in s for x in ["não vendido", "unsold", "sem lance"]):
            return "unsold"
        
        # Ao vivo
        if any(x in s for x in ["ao vivo", "live", "em andamento"]):
            return "live"
        
        # Encerrado
        if any(x in s for x in ["encerrado", "ended", "finalizado"]):
            return "ended"
        
        # Cancelado
        if any(x in s for x in ["cancelado", "cancelled"]):
            return "cancelled"
        
        # Agendado
        if any(x in s for x in ["agendado", "scheduled", "próximo"]):
            return "scheduled"
        
        return "scheduled"
    
    def _normalize_item_type(self, s: str) -> str:
        """Normaliza tipo de item.
        
        Returns:
            vehicle | motorcycle | boat | other
        """
        if not s:
            return "vehicle"
        
        s = s.lower()
        
        if any(x in s for x in ["carro", "veículo", "vehicle", "automóvel"]):
            return "vehicle"
        
        if any(x in s for x in ["moto", "motorcycle"]):
            return "motorcycle"
        
        if any(x in s for x in ["barco", "lancha", "boat"]):
            return "boat"
        
        return "other"
    
    def _normalize_condition(self, s: str) -> Optional[str]:
        """Normaliza condição do bem.
        
        Returns:
            new | used | damaged | salvage | None
        """
        if not s:
            return None
        
        s = s.lower()
        
        if any(x in s for x in ["novo", "new", "0 km"]):
            return "new"
        
        if any(x in s for x in ["sinistro", "salvage", "leilão de seguro"]):
            return "salvage"
        
        if any(x in s for x in ["avariado", "damaged", "batido"]):
            return "damaged"
        
        if any(x in s for x in ["usado", "used", "seminovo"]):
            return "used"
        
        return None
    
    def _extract_lot_number(self, s: str) -> Optional[str]:
        """Extrai número do lote."""
        if not s:
            return None
        
        import re
        
        # Formato comum: "Lote 123" ou "123"
        m = re.search(r'(?:lote|lot)\s*[:\s]?\s*(\d+)', s, re.I)
        if m:
            return m.group(1)
        
        # Apenas número
        m = re.search(r'\b(\d{1,6})\b', s)
        if m:
            return m.group(1)
        
        return None
    
    def _parse_boolean_field(self, s: str) -> Optional[bool]:
        """Parse campo booleano."""
        if not s:
            return None
        
        s = s.lower().strip()
        
        if s in ["sim", "yes", "s", "y", "true", "1", "possui"]:
            return True
        
        if s in ["não", "no", "n", "false", "0", "não possui"]:
            return False
        
        return None
