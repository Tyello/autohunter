"""
Scraper para OLX - Hybrid (HTTP + Browser Fallback).

Características:
- API pública (quando funciona)
- HTTP preferencial
- Browser fallback quando bloqueado (~30% das vezes)
- Parsing JSON + HTML
"""

from __future__ import annotations
from decimal import Decimal
from typing import Dict, Any, List, Optional
import re
import json

from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin, urlparse

from app.scrapers.scraper_base import BaseScraper


class OLXScraper(BaseScraper):
    """Scraper para OLX (Hybrid).
    
    URL base: https://www.olx.com.br
    Método: HTTP (API JSON) + Browser fallback
    """
    
    BASE_URL = "https://www.olx.com.br"
    API_URL = "https://www.olx.com.br/api/v1/search/listings"
    
    def __init__(self):
        super().__init__(source_name="olx")
    
    def build_search_url(self, query: str, **kwargs) -> str:
        """Constrói URL de busca para OLX.
        
        OLX tem API v1 pública (quando não bloqueia).
        
        Args:
            query: Termo de busca
            **kwargs: category (default: "autos-e-pecas/carros-vans-e-utilitarios")
        
        Returns:
            URL da API ou do site
        """
        q = quote_plus(query.strip())
        category = kwargs.get("category", "autos-e-pecas/carros-vans-e-utilitarios")
        
        # Tenta API primeiro (mais limpo)
        url = f"{self.API_URL}?q={q}&category={category}&limit=50"
        
        return url
    
    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        """Extrai items do JSON ou HTML (fallback).
        
        OLX pode retornar:
        1. JSON da API (quando HTTP funciona)
        2. HTML (quando bloqueado e usa browser)
        """
        # Tenta JSON primeiro
        try:
            data = json.loads(raw_content)
            
            # API response format
            listings = data.get("data", {}).get("listings", [])
            if listings:
                return listings
            
            # Formato alternativo
            if "ads" in data:
                return data["ads"]
            
            # Se JSON mas vazio, continua para HTML
        except json.JSONDecodeError:
            pass
        
        # Fallback: HTML parsing (browser foi usado)
        return self._extract_from_html(raw_content)
    
    def _extract_from_html(self, html: str) -> List[Dict]:
        """Extrai anúncios do HTML (quando browser é usado)."""
        soup = BeautifulSoup(html, "lxml")
        
        items = []
        
        # OLX usa data-id nos cards
        cards = soup.select("[data-ds-component='DS-AdCard']")
        
        if not cards:
            # Fallback: outros seletores
            cards = soup.select(".olx-ad-card, .fnmrjs-0, article[data-id]")
        
        for card in cards:
            try:
                # Link
                link_el = card.select_one("a[href]")
                if not link_el:
                    continue
                
                url = link_el.get("href", "")
                if not url.startswith("http"):
                    url = urljoin(self.BASE_URL, url)
                
                # ID do data-id
                item_id = card.get("data-id") or card.get("id", "")
                
                # Título
                title_el = card.select_one("h2, h3, [data-ds-component='DS-Text']")
                title = title_el.get_text(strip=True) if title_el else ""
                
                # Preço
                price_el = card.select_one("[data-ds-component='DS-Price']")
                if not price_el:
                    price_el = card.select_one(".olx-ad-card__price")
                price_text = price_el.get_text(strip=True) if price_el else ""
                
                # Localização
                location_el = card.select_one("[data-ds-component='DS-Location']")
                if not location_el:
                    location_el = card.select_one(".olx-ad-card__location")
                location = location_el.get_text(strip=True) if location_el else ""
                
                # Imagem
                img_el = card.select_one("img")
                thumbnail = ""
                if img_el:
                    thumbnail = img_el.get("src") or img_el.get("data-src") or ""
                
                # Atributos (ano, km podem estar em pills/tags)
                attrs_el = card.select(".olx-ad-card__attribute, [data-ds-component='DS-Tag']")
                attrs = [el.get_text(strip=True) for el in attrs_el]
                
                items.append({
                    "id": item_id,
                    "url": url,
                    "title": title,
                    "price": price_text,
                    "location": location,
                    "thumbnail": thumbnail,
                    "attributes": attrs,
                })
                
            except Exception:
                continue
        
        return items
    
    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normaliza dados de um anúncio da OLX.
        
        Args:
            raw_data: Item da API ou HTML
        
        Returns:
            Dict normalizado ou None
        """
        try:
            # ID e URL
            external_id = str(raw_data.get("id") or raw_data.get("ad_id") or "")
            if not external_id:
                return None
            
            url = raw_data.get("url") or raw_data.get("link") or ""
            if not url or not url.startswith("http"):
                return None
            
            # Título
            title = raw_data.get("title") or raw_data.get("subject") or ""
            title = title.strip()
            
            # Preço
            price = None
            price_data = raw_data.get("price")
            
            if isinstance(price_data, dict):
                # API format: {"value": 50000, "currency": "BRL"}
                price_value = price_data.get("value")
                if price_value:
                    try:
                        price = Decimal(str(price_value))
                    except:
                        pass
            elif isinstance(price_data, (int, float)):
                try:
                    price = Decimal(str(price_data))
                except:
                    pass
            elif isinstance(price_data, str):
                price = self._parse_price(price_data)
            
            # Localização
            location_data = raw_data.get("location") or raw_data.get("region")
            location = None
            
            if isinstance(location_data, dict):
                city = location_data.get("city", "")
                state = location_data.get("state", "")
                if city and state:
                    location = f"{city}, {state}"
                elif city:
                    location = city
            elif isinstance(location_data, str):
                location = location_data.strip()
            
            # Thumbnail
            thumbnail = None
            images = raw_data.get("images") or raw_data.get("thumbnail")
            
            if isinstance(images, list) and images:
                thumbnail = images[0] if isinstance(images[0], str) else images[0].get("url")
            elif isinstance(images, str):
                thumbnail = images
            
            # Atributos (properties da API ou attributes do HTML)
            properties = raw_data.get("properties", [])
            attributes = raw_data.get("attributes", [])
            
            # Extrai campos específicos
            year = self._extract_property(properties, "year") or self._extract_from_title(title, "year")
            mileage_km = self._extract_property(properties, "mileage") or self._extract_from_title(title, "km")
            make = self._extract_property(properties, "make")
            model = self._extract_property(properties, "model")
            fuel_type = self._extract_property(properties, "fuel")
            transmission = self._extract_property(properties, "transmission")
            
            # Normaliza
            if year:
                year = self._parse_year(year)
            if mileage_km:
                mileage_km = self._parse_km(str(mileage_km))
            if fuel_type:
                fuel_type = self._normalize_fuel(fuel_type)
            if transmission:
                transmission = self._normalize_transmission(transmission)
            
            # Extrai make/model do título se não vier da API
            if not make or not model:
                title_make, title_model = self._extract_make_model(title)
                make = make or title_make
                model = model or title_model
            
            return {
                "external_id": external_id,
                "title": title,
                "url": url,
                "thumbnail_url": thumbnail,
                "price": price,
                "location": location,
                "year": year,
                "mileage_km": mileage_km,
                "make": make,
                "model": model,
                "fuel_type": fuel_type,
                "transmission": transmission,
                "extractor_version": "olx_v1",
                "extras": {
                    "properties": properties,
                    "attributes": attributes,
                },
                "raw_payload": raw_data,
            }
            
        except Exception as e:
            return None
    
    # ========== Helper Methods ==========
    
    def _extract_property(self, properties: List, key: str) -> Optional[str]:
        """Extrai propriedade da lista (API format)."""
        if not properties:
            return None
        
        for prop in properties:
            if isinstance(prop, dict):
                prop_name = prop.get("name", "").lower()
                if key in prop_name:
                    return prop.get("value")
        
        return None
    
    def _extract_from_title(self, title: str, field: str) -> Optional[Any]:
        """Extrai campo do título (fallback)."""
        if not title:
            return None
        
        if field == "year":
            m = re.search(r'\b(19\d{2}|20\d{2})\b', title)
            return m.group(1) if m else None
        
        if field == "km":
            # "50mil km", "50.000km", etc
            m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:mil)?\s*k', title, re.I)
            if m:
                return m.group(0)
        
        return None
    
    def _parse_price(self, s: str) -> Optional[Decimal]:
        """Parse preço."""
        if not s:
            return None
        
        s = s.replace("R$", "").replace("$", "").strip()
        s = s.replace(".", "").replace(",", ".")
        s = re.sub(r'[^\d.]', '', s)
        
        if not s:
            return None
        
        try:
            return Decimal(s)
        except:
            return None
    
    def _parse_year(self, value: Any) -> Optional[int]:
        """Parse ano."""
        if isinstance(value, int):
            if 1980 <= value <= 2030:
                return value
            return None
        
        if isinstance(value, str):
            m = re.search(r'(19\d{2}|20\d{2})', value)
            if m:
                try:
                    year = int(m.group(1))
                    if 1980 <= year <= 2030:
                        return year
                except:
                    pass
        
        return None
    
    def _parse_km(self, s: str) -> Optional[int]:
        """Parse quilometragem."""
        if not s:
            return None
        
        s = s.lower()
        
        # "50 mil km"
        if "mil" in s:
            m = re.search(r'(\d+(?:[,.]\d+)?)\s*mil', s)
            if m:
                try:
                    num = float(m.group(1).replace(",", "."))
                    return int(num * 1000)
                except:
                    pass
        
        # Remove tudo exceto dígitos
        s = re.sub(r'[^\d]', '', s)
        
        if not s:
            return None
        
        try:
            return int(s)
        except:
            return None
    
    def _extract_make_model(self, title: str) -> tuple[Optional[str], Optional[str]]:
        """Extrai marca e modelo do título."""
        if not title:
            return None, None
        
        brands = [
            "honda", "toyota", "volkswagen", "vw", "ford", "chevrolet",
            "fiat", "hyundai", "nissan", "renault", "peugeot", "citroën",
            "jeep", "bmw", "mercedes", "audi", "volvo", "mitsubishi",
            "suzuki", "kia", "chery", "caoa", "ram"
        ]
        
        title_lower = title.lower()
        
        make = None
        for brand in brands:
            if brand in title_lower:
                make = brand.capitalize()
                if brand == "vw":
                    make = "Volkswagen"
                break
        
        if make:
            idx = title_lower.find(make.lower())
            if idx >= 0:
                after = title[idx + len(make):].strip()
                words = after.split()
                if words:
                    model = words[0].capitalize()
                    return make, model
        
        return make, None
    
    def _normalize_fuel(self, s: str) -> Optional[str]:
        """Normaliza combustível."""
        if not s:
            return None
        
        s = s.lower()
        
        if "flex" in s:
            return "flex"
        if "gasolina" in s:
            return "gasoline"
        if "etanol" in s or "álcool" in s:
            return "ethanol"
        if "diesel" in s:
            return "diesel"
        if "elétric" in s:
            return "electric"
        if "híbrid" in s:
            return "hybrid"
        
        return None
    
    def _normalize_transmission(self, s: str) -> Optional[str]:
        """Normaliza transmissão."""
        if not s:
            return None
        
        s = s.lower()
        
        if "manual" in s or "mecânica" in s:
            return "manual"
        if "automát" in s or "cvt" in s:
            return "automatic"
        
        return None
