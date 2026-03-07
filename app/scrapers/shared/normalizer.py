"""
Normalizer - Validação e normalização de campos de listings.

Garante que todos os listings tenham campos consistentes e válidos.
"""

from __future__ import annotations
from typing import Dict, Any, Optional
from decimal import Decimal

from app.common.price_parser import parse_price_decimal


# Campos obrigatórios
REQUIRED_FIELDS = {"source", "external_id", "url"}

# Campos opcionais com tipo esperado
OPTIONAL_FIELDS = {
    "title": str,
    "thumbnail_url": str,
    "price": (Decimal, float, int),
    "currency": str,
    "location": str,
    "year": int,
    "mileage_km": int,
    "make": str,
    "model": str,
    "fuel_type": str,
    "transmission": str,
    "listing_type": str,
    "extractor_version": str,
    "extras": dict,
    "raw_payload": (dict, str),
}


def validate_listing(listing: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Valida um listing (campos obrigatórios presentes).
    
    Args:
        listing: Dicionário com dados do listing
    
    Returns:
        (is_valid, error_message)
    """
    # Check required fields
    for field in REQUIRED_FIELDS:
        if field not in listing or not listing[field]:
            return False, f"Missing required field: {field}"
    
    # Validate source
    source = listing.get("source", "")
    if not isinstance(source, str) or len(source) == 0:
        return False, "Invalid source"
    
    # Validate external_id
    external_id = listing.get("external_id", "")
    if not isinstance(external_id, str) or len(external_id) == 0:
        return False, "Invalid external_id"
    
    # Validate URL
    url = listing.get("url", "")
    if not isinstance(url, str) or not url.startswith("http"):
        return False, "Invalid url"
    
    return True, None


def normalize_listing(listing: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza campos de um listing.
    
    - Remove campos None/vazios
    - Converte tipos quando possível
    - Adiciona defaults
    
    Args:
        listing: Dicionário bruto
    
    Returns:
        Dicionário normalizado
    """
    normalized = {}
    
    # Copia campos obrigatórios
    for field in REQUIRED_FIELDS:
        if field in listing:
            normalized[field] = listing[field]
    
    # Processa campos opcionais
    for field, expected_type in OPTIONAL_FIELDS.items():
        if field not in listing:
            continue
        
        value = listing[field]
        
        # Skip None ou vazios
        if value is None or value == "":
            continue
        
        # Conversão de tipo
        if field == "price":
            value = _normalize_price(value)
        elif field == "year":
            value = _normalize_year(value)
        elif field == "mileage_km":
            value = _normalize_mileage(value)
        elif field == "extras" and not isinstance(value, dict):
            value = {"raw": str(value)}
        
        if value is not None:
            normalized[field] = value
    
    # Defaults
    if "currency" not in normalized:
        normalized["currency"] = "BRL"
    
    if "listing_type" not in normalized:
        normalized["listing_type"] = "marketplace"
    
    return normalized


def _normalize_price(value: Any) -> Optional[Decimal]:
    """Converte preço para Decimal usando parser central."""
    return parse_price_decimal(value)


def _normalize_year(value: Any) -> Optional[int]:
    """Converte ano para int."""
    if isinstance(value, int):
        # Validação básica (1900-2100)
        if 1900 <= value <= 2100:
            return value
        return None
    
    if isinstance(value, str):
        try:
            year = int(value)
            if 1900 <= year <= 2100:
                return year
        except ValueError:
            pass
    
    return None


def _normalize_mileage(value: Any) -> Optional[int]:
    """Converte quilometragem para int."""
    if isinstance(value, int):
        return max(0, value)
    
    if isinstance(value, str):
        # Remove pontos/vírgulas
        clean = value.replace(".", "").replace(",", "").replace("km", "").strip()
        
        try:
            return max(0, int(clean))
        except ValueError:
            pass
    
    return None
