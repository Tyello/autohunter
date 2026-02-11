"""
Scraper para Webmotors - Browser Required.

Características:
- SPA React (client-side rendering)
- PerimeterX anti-bot protection
- Browser obrigatório
- API interna (precisa de headers específicos)
"""

from __future__ import annotations
from decimal import Decimal
from typing import Dict, Any, List, Optional
import re
import json

from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

from app.scrapers.scraper_base import BaseScraper


class WebmotorsScraper(BaseScraper):
    """Scraper para Webmotors (Browser Required).
    
    URL base: https://www.webmotors.com.br
    Método: Browser only (SPA React + PerimeterX)
    """
    
    BASE_URL = "https://www.webmotors.com.br"
    
    def __init__(self):
        super().__init__(source_name="webmotors")
    
    def build_search_url(self, query: str, **kwargs) -> str:
        """Constrói URL de busca para Webmotors.
        
        Webmotors usa SPA, então URL é tradicional mas conteúdo
        é carregado via JS.
        
        Args:
            query: Termo de busca
            **kwargs: tipoVeiculo (default: "carros")
        
        Returns:
            URL do site
        """
        tipo = kwargs.get("tipoVeiculo", "carros")
        
        # URL format: /comprar/carros/honda-civic?
        # Simplificado: usa busca geral
        q = query.replace(" ", "-").lower()
        
        url = f"{self.BASE_URL}/comprar/{tipo}?q={q}"
        
        return url
    
    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        """Extrai items do HTML renderizado (via browser).
        
        Webmotors carrega dados via React, então HTML já vem
        renderizado pelo Playwright.
        """
        soup = BeautifulSoup(raw_content, "lxml")
        
        items = []
        
        # Webmotors usa data-type="car-card"
        cards = soup.select("[data-type='car-card'], .card-vehicle")
        
        if not cards:
            # Fallback: busca por estrutura
            cards = soup.select("article, .vehicle-card, [data-testid*='card']")
        
        for card in cards:
            try:
                # Link principal
                link_el = card.select_one("a[href*='/comprar/']")
                if not link_el:
                    link_el = card.select_one("a[href]")
                
                if not link_el:
                    continue
                
                url = link_el.get("href", "")
                if not url.startswith("http"):
                    url = urljoin(self.BASE_URL, url)
                
                # Título
                title_el = card.select_one("h2, h3, .card-title, [data-testid='vehicle-name']")
                title = title_el.get_text(strip=True) if title_el else ""
                
                # Preço
                price_el = card.select_one(".card-price, [data-testid='price'], .vehicle-price")
                price_text = price_el.get_text(strip=True) if price_el else ""
                
                # Ano/KM (geralmente em linha)
                year_el = card.select_one("[data-testid='year'], .vehicle-year")
                year_text = year_el.get_text(strip=True) if year_el else ""
                
                km_el = card.select_one("[data-testid='km'], .vehicle-km")
                km_text = km_el.get_text(strip=True) if km_el else ""
                
                # Localização
                location_el = card.select_one(".card-location, [data-testid='location']")
                location = location_el.get_text(strip=True) if location_el else ""
                
                # Imagem
                img_el = card.select_one("img")
                thumbnail = ""
                if img_el:
                    thumbnail = img_el.get("src") or img_el.get("data-src") or ""
                
                # Atributos adicionais
                attrs = []
                attr_els = card.select(".vehicle-attribute, [data-testid*='attribute']")
                for el in attr_els:
                    attrs.append(el.get_text(strip=True))
                
                items.append({
                    "url": url,
                    "title": title,
                    "price": price_text,
                    "year": year_text,
                    "mileage": km_text,
                    "location": location,
                    "thumbnail": thumbnail,
                    "attributes": attrs,
                })
                
            except Exception:
                continue
        
        return items
    
    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normaliza dados de um anúncio do Webmotors.
        
        Args:
            raw_data: Dict extraído do HTML
        
        Returns:
            Dict normalizado ou None
        """
        try:
            url = raw_data.get("url", "")
            if not url or not url.startswith("http"):
                return None
            
            # External ID do URL
            external_id = self._extract_id_from_url(url)
            if not external_id:
                return None
            
            # Título
            title = raw_data.get("title", "").strip()
            
            # Preço
            price = self._parse_price(raw_data.get("price", ""))
            
            # Ano
            year = self._parse_year(raw_data.get("year", ""))
            
            # KM
            mileage_km = self._parse_km(raw_data.get("mileage", ""))
            
            # Thumbnail
            thumbnail = raw_data.get("thumbnail", "")
            if thumbnail and not thumbnail.startswith("http"):
                thumbnail = urljoin(self.BASE_URL, thumbnail)
            
            # Extrai make/model do título
            make, model = self._extract_make_model(title)
            
            # Atributos
            attributes = raw_data.get("attributes", [])
            transmission = self._extract_transmission_from_attrs(attributes)
            fuel_type = self._extract_fuel_from_attrs(attributes)
            
            return {
                "external_id": external_id,
                "title": title,
                "url": url,
                "thumbnail_url": thumbnail or None,
                "price": price,
                "location": raw_data.get("location", "").strip() or None,
                "year": year,
                "mileage_km": mileage_km,
                "make": make,
                "model": model,
                "transmission": transmission,
                "fuel_type": fuel_type,
                "extractor_version": "webmotors_v1",
                "extras": {
                    "attributes": attributes,
                },
                "raw_payload": raw_data,
            }
            
        except Exception:
            return None
    
    # ========== Helper Methods ==========
    
    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrai ID do URL.
        
        Webmotors URL: /comprar/honda/civic/1.8-lx-16v-flex-4p-automatico/4-portas/2019/123456
        """
        m = re.search(r'/(\d+)/?$', url)
        if m:
            return m.group(1)
        
        # Fallback: hash
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()[:16]
    
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
    
    def _parse_year(self, s: str) -> Optional[int]:
        """Parse ano."""
        if not s:
            return None
        
        m = re.search(r'(19\d{2}|20\d{2})', s)
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
        
        if "mil" in s:
            m = re.search(r'(\d+(?:[,.]\d+)?)\s*mil', s)
            if m:
                try:
                    num = float(m.group(1).replace(",", "."))
                    return int(num * 1000)
                except:
                    pass
        
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
    
    def _extract_transmission_from_attrs(self, attrs: List[str]) -> Optional[str]:
        """Extrai transmissão dos atributos."""
        if not attrs:
            return None
        
        for attr in attrs:
            attr_lower = attr.lower()
            if "manual" in attr_lower or "mecânica" in attr_lower:
                return "manual"
            if "automát" in attr_lower or "cvt" in attr_lower:
                return "automatic"
        
        return None
    
    def _extract_fuel_from_attrs(self, attrs: List[str]) -> Optional[str]:
        """Extrai combustível dos atributos."""
        if not attrs:
            return None
        
        for attr in attrs:
            attr_lower = attr.lower()
            if "flex" in attr_lower:
                return "flex"
            if "gasolina" in attr_lower:
                return "gasoline"
            if "etanol" in attr_lower or "álcool" in attr_lower:
                return "ethanol"
            if "diesel" in attr_lower:
                return "diesel"
            if "elétric" in attr_lower:
                return "electric"
            if "híbrid" in attr_lower:
                return "hybrid"
        
        return None
