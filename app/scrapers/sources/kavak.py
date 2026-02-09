"""
Scraper para Kavak - HTTP API.

Características:
- API REST pública
- JSON limpo
- HTTP estável
"""

from __future__ import annotations
from decimal import Decimal
from typing import Dict, Any, List, Optional
import re
import json

from urllib.parse import quote_plus

from app.scrapers.scraper_base import BaseScraper


class KavakScraper(BaseScraper):
    """Scraper para Kavak (HTTP API).
    
    URL base: https://www.kavak.com/br
    Método: HTTP (API REST)
    """
    
    BASE_URL = "https://www.kavak.com/br"
    API_URL = "https://www.kavak.com/api/br/v1/vehicles"
    
    def __init__(self):
        super().__init__(source_name="kavak")
    
    def build_search_url(self, query: str, **kwargs) -> str:
        """Constrói URL de busca para Kavak.
        
        Kavak tem API REST.
        
        Args:
            query: Termo de busca
        
        Returns:
            URL da API
        """
        # Kavak usa filters, não query string
        # Por simplicidade, usamos query geral
        url = f"{self.API_URL}?search={quote_plus(query)}&limit=50"
        return url
    
    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        """Extrai items do JSON da API."""
        try:
            data = json.loads(raw_content)
            
            # Formato Kavak: {"vehicles": [...]}
            vehicles = data.get("vehicles") or data.get("data") or data.get("results")
            
            if isinstance(vehicles, list):
                return vehicles
            
            return []
            
        except json.JSONDecodeError:
            return []
    
    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normaliza dados de um veículo da Kavak."""
        try:
            # ID
            external_id = str(raw_data.get("id") or raw_data.get("vehicle_id") or "")
            if not external_id:
                return None
            
            # URL
            slug = raw_data.get("slug") or raw_data.get("url_slug") or ""
            if slug:
                url = f"{self.BASE_URL}/comprar/{slug}"
            else:
                url = f"{self.BASE_URL}/vehicle/{external_id}"
            
            # Título (make + model + year)
            make = raw_data.get("make") or raw_data.get("brand") or ""
            model = raw_data.get("model") or ""
            year = raw_data.get("year")
            
            if make and model and year:
                title = f"{make} {model} {year}"
            else:
                title = raw_data.get("title") or raw_data.get("name") or f"{make} {model}".strip()
            
            # Preço
            price = None
            price_data = raw_data.get("price")
            
            if isinstance(price_data, (int, float)):
                price = Decimal(str(price_data))
            elif isinstance(price_data, dict):
                price_value = price_data.get("value") or price_data.get("amount")
                if price_value:
                    price = Decimal(str(price_value))
            
            # Localização
            location_data = raw_data.get("location") or raw_data.get("store")
            location = None
            
            if isinstance(location_data, dict):
                city = location_data.get("city")
                state = location_data.get("state")
                if city and state:
                    location = f"{city}, {state}"
                elif city:
                    location = city
            elif isinstance(location_data, str):
                location = location_data
            
            # Thumbnail
            thumbnail = None
            images = raw_data.get("images") or raw_data.get("photos")
            
            if isinstance(images, list) and images:
                first_img = images[0]
                thumbnail = first_img if isinstance(first_img, str) else first_img.get("url")
            elif isinstance(images, str):
                thumbnail = images
            
            # Quilometragem
            mileage_km = raw_data.get("mileage") or raw_data.get("odometer")
            if mileage_km:
                mileage_km = int(mileage_km)
            
            # Combustível
            fuel_type = raw_data.get("fuel") or raw_data.get("fuel_type")
            if fuel_type:
                fuel_type = self._normalize_fuel(fuel_type)
            
            # Transmissão
            transmission = raw_data.get("transmission")
            if transmission:
                transmission = self._normalize_transmission(transmission)
            
            return {
                "external_id": external_id,
                "title": title,
                "url": url,
                "thumbnail_url": thumbnail,
                "price": price,
                "location": location,
                "year": int(year) if year else None,
                "mileage_km": mileage_km,
                "make": make,
                "model": model,
                "fuel_type": fuel_type,
                "transmission": transmission,
                "extractor_version": "kavak_v1",
                "extras": {
                    "color": raw_data.get("color"),
                    "engine": raw_data.get("engine"),
                    "doors": raw_data.get("doors"),
                },
                "raw_payload": raw_data,
            }
            
        except Exception:
            return None
    
    # ========== Helpers ==========
    
    def _normalize_fuel(self, s: str) -> Optional[str]:
        """Normaliza combustível."""
        if not s:
            return None
        
        s = s.lower()
        
        if "flex" in s:
            return "flex"
        if "gasolina" in s or "gasoline" in s:
            return "gasoline"
        if "etanol" in s or "ethanol" in s:
            return "ethanol"
        if "diesel" in s:
            return "diesel"
        if "elétric" in s or "electric" in s:
            return "electric"
        if "híbrid" in s or "hybrid" in s:
            return "hybrid"
        
        return None
    
    def _normalize_transmission(self, s: str) -> Optional[str]:
        """Normaliza transmissão."""
        if not s:
            return None
        
        s = s.lower()
        
        if "manual" in s:
            return "manual"
        if "automát" in s or "automatic" in s or "cvt" in s:
            return "automatic"
        
        return None
