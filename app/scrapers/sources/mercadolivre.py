"""
Scraper para Mercado Livre - Hybrid (HTTP + Browser Fallback).

Características:
- API pública (JSON)
- HTTP preferencial
- Browser fallback quando bloqueado
- Usa estratégias múltiplas (HTTP → curl_cffi → browser)
"""

from __future__ import annotations
from decimal import Decimal
from typing import Dict, Any, List, Optional
import re
import json

from urllib.parse import urlparse, urlunparse, quote_plus

from app.scrapers.scraper_base import BaseScraper


class MercadoLivreScraper(BaseScraper):
    """Scraper para Mercado Livre (Hybrid).
    
    URL base: https://www.mercadolivre.com.br
    Método: HTTP (API JSON) + Browser fallback
    """
    
    BASE_URL = "https://www.mercadolivre.com.br"
    API_URL = "https://api.mercadolibre.com/sites/MLB/search"
    
    # Apenas anúncios do vertical de veículos
    ALLOWED_VEHICLE_HOSTS = {"carro.mercadolivre.com.br"}
    
    def __init__(self):
        super().__init__(source_name="mercadolivre")
    
    def build_search_url(self, query: str, **kwargs) -> str:
        """Constrói URL de busca para Mercado Livre.
        
        Usa API pública: /sites/MLB/search?q=civic+si&category=MLB1743
        
        Args:
            query: Termo de busca
            **kwargs: limit (default: 50)
        
        Returns:
            URL da API
        """
        q = quote_plus(query.strip())
        limit = kwargs.get("limit", 50)
        
        # Category MLB1743 = Carros, Motos e Outros
        url = f"{self.API_URL}?q={q}&category=MLB1743&limit={limit}"
        
        return url
    
    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        """Extrai items do JSON da API.
        
        Response format:
        {
            "results": [
                {
                    "id": "MLB123",
                    "title": "Honda Civic",
                    "price": 50000,
                    "permalink": "https://...",
                    ...
                }
            ]
        }
        """
        try:
            data = json.loads(raw_content)
            results = data.get("results", [])
            
            # Filtra apenas veículos (não peças/acessórios)
            vehicles = []
            for item in results:
                permalink = item.get("permalink", "")
                
                # Verifica se é anúncio de veículo (não produto/peça)
                if self._is_vehicle_listing(permalink):
                    vehicles.append(item)
            
            return vehicles
            
        except json.JSONDecodeError:
            # Se não é JSON, pode ser HTML (bloqueio)
            # Retorna vazio - BaseScraper vai tentar fallback
            return []
    
    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normaliza dados de um anúncio do Mercado Livre.
        
        Args:
            raw_data: Item da API
        
        Returns:
            Dict normalizado
        """
        try:
            # ID e URL
            external_id = raw_data.get("id", "")
            if not external_id:
                return None
            
            permalink = raw_data.get("permalink", "")
            if not permalink:
                return None
            
            # Remove tracking/query params
            url = self._clean_url(permalink)
            
            # Skip tracking URLs
            if self._is_tracking_url(url):
                return None
            
            # Título
            title = raw_data.get("title", "").strip()
            
            # Preço
            price = raw_data.get("price")
            if price is not None:
                try:
                    price = Decimal(str(price))
                except:
                    price = None
            
            # Currency
            currency = raw_data.get("currency_id", "BRL")
            if currency == "BRL":
                currency = "BRL"
            else:
                currency = "BRL"  # default
            
            # Thumbnail
            thumbnail = raw_data.get("thumbnail")
            if thumbnail:
                # ML thumbnail pode vir como http, trocar para https
                thumbnail = thumbnail.replace("http://", "https://")
            
            # Localização
            location_data = raw_data.get("location", {})
            if isinstance(location_data, dict):
                city = location_data.get("city", {})
                state = location_data.get("state", {})
                
                city_name = city.get("name", "") if isinstance(city, dict) else ""
                state_name = state.get("name", "") if isinstance(state, dict) else ""
                
                if city_name and state_name:
                    location = f"{city_name}, {state_name}"
                elif city_name:
                    location = city_name
                elif state_name:
                    location = state_name
                else:
                    location = None
            else:
                location = None
            
            # Atributos (ano, km, etc em attributes array)
            attributes = raw_data.get("attributes", [])
            year = self._extract_attribute(attributes, "VEHICLE_YEAR")
            mileage_km = self._extract_attribute(attributes, "KILOMETERS")
            make = self._extract_attribute(attributes, "BRAND")
            model = self._extract_attribute(attributes, "MODEL")
            fuel_type = self._extract_attribute(attributes, "FUEL_TYPE")
            transmission = self._extract_attribute(attributes, "TRANSMISSION")
            
            # Normaliza valores
            if year:
                year = self._parse_year(year)
            
            if mileage_km:
                mileage_km = self._parse_km(str(mileage_km))
            
            if fuel_type:
                fuel_type = self._normalize_fuel(fuel_type)
            
            if transmission:
                transmission = self._normalize_transmission(transmission)
            
            return {
                "external_id": external_id,
                "title": title,
                "url": url,
                "thumbnail_url": thumbnail,
                "price": price,
                "currency": currency,
                "location": location,
                "year": year,
                "mileage_km": mileage_km,
                "make": make,
                "model": model,
                "fuel_type": fuel_type,
                "transmission": transmission,
                "extractor_version": "mercadolivre_v1",
                "extras": {
                    "seller_id": raw_data.get("seller", {}).get("id"),
                    "condition": raw_data.get("condition"),
                    "listing_type": raw_data.get("listing_type_id"),
                    "accepts_mercadopago": raw_data.get("accepts_mercadopago"),
                },
                "raw_payload": raw_data,
            }
            
        except Exception as e:
            return None
    
    # ========== Helper Methods ==========
    
    def _is_vehicle_listing(self, url: str) -> bool:
        """Verifica se URL é de veículo (não peça/acessório).
        
        Veículos: carro.mercadolivre.com.br
        Produtos: produto.mercadolivre.com.br ou mercadolivre.com.br/p/
        """
        if not url:
            return False
        
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            
            # Apenas hosts de veículos
            return host in self.ALLOWED_VEHICLE_HOSTS
            
        except:
            return False
    
    def _is_tracking_url(self, url: str) -> bool:
        """Detecta URLs de tracking patrocinado."""
        if not url:
            return False
        
        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            path = parsed.path.lower()
            
            # Tracking domains
            if host.startswith("click") or host.startswith("clk"):
                return True
            
            # Tracking paths
            if "brand_ads/clicks" in path or "/ads/" in path:
                return True
            
        except:
            pass
        
        return False
    
    def _clean_url(self, url: str) -> str:
        """Remove query params e fragment para evitar duplicação."""
        if not url:
            return ""
        
        try:
            parsed = urlparse(url)
            # Mantém apenas scheme, netloc, path
            clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
            return clean
        except:
            # Fallback: remove manualmente
            return url.split("?")[0].split("#")[0]
    
    def _extract_attribute(self, attributes: List[Dict], attr_id: str) -> Optional[Any]:
        """Extrai valor de um atributo da lista.
        
        attributes = [
            {"id": "VEHICLE_YEAR", "value_name": "2019"},
            {"id": "KILOMETERS", "value_name": "50000"},
            ...
        ]
        """
        if not attributes:
            return None
        
        for attr in attributes:
            if isinstance(attr, dict) and attr.get("id") == attr_id:
                # Tenta value_name primeiro, depois value_id
                value = attr.get("value_name") or attr.get("value_id")
                return value
        
        return None
    
    def _parse_year(self, value: Any) -> Optional[int]:
        """Parse ano."""
        if value is None:
            return None
        
        try:
            year = int(value)
            if 1980 <= year <= 2030:
                return year
        except:
            pass
        
        return None
    
    def _parse_km(self, s: str) -> Optional[int]:
        """Parse quilometragem."""
        if not s:
            return None
        
        # Remove não-dígitos
        s = re.sub(r'[^\d]', '', s)
        
        if not s:
            return None
        
        try:
            return int(s)
        except:
            return None
    
    def _normalize_fuel(self, s: str) -> Optional[str]:
        """Normaliza tipo de combustível.
        
        ML usa: "Nafta", "Flex", "Diesel", etc
        """
        if not s:
            return None
        
        s = s.lower()
        
        if "flex" in s:
            return "flex"
        
        if "nafta" in s or "gasolina" in s or "gasoline" in s:
            return "gasoline"
        
        if "etanol" in s or "álcool" in s or "alcool" in s:
            return "ethanol"
        
        if "diesel" in s or "óleo" in s or "gasoil" in s:
            return "diesel"
        
        if "elétric" in s or "electric" in s or "ev" in s:
            return "electric"
        
        if "híbrid" in s or "hybrid" in s:
            return "hybrid"
        
        return None
    
    def _normalize_transmission(self, s: str) -> Optional[str]:
        """Normaliza transmissão.
        
        ML usa: "Manual", "Automática", etc
        """
        if not s:
            return None
        
        s = s.lower()
        
        if "manual" in s or "mecânica" in s:
            return "manual"
        
        if "automát" in s or "automática" in s or "cvt" in s:
            return "automatic"
        
        return None
