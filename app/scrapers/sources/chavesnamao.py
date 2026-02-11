"""
Scraper para Chaves na Mão - HTTP-only.

Características:
- SSR tradicional
- HTTP estável
- Parsing HTML simples
"""

from __future__ import annotations
from decimal import Decimal
from typing import Dict, Any, List, Optional
import re

from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

from app.scrapers.scraper_base import BaseScraper


class ChavesNaMaoScraper(BaseScraper):
    """Scraper para Chaves na Mão (HTTP-only).
    
    URL base: https://www.chavesnamao.com.br
    Método: HTTP + BeautifulSoup
    """
    
    BASE_URL = "https://www.chavesnamao.com.br"
    
    def __init__(self):
        super().__init__(source_name="chavesnamao")
    
    def build_search_url(self, query: str, **kwargs) -> str:
        """Constrói URL de busca para Chaves na Mão.
        
        Args:
            query: Termo de busca
        
        Returns:
            URL de busca
        """
        q = quote_plus(query.strip())
        url = f"{self.BASE_URL}/busca?q={q}"
        return url
    
    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        """Extrai anúncios do HTML."""
        soup = BeautifulSoup(raw_content, "lxml")
        
        items = []
        
        # Chaves na Mão usa classes específicas
        cards = soup.select(".vehicle-card, .card-veiculo, article.veiculo")
        
        if not cards:
            cards = soup.select("[data-vehicle-id]")
        
        for card in cards:
            try:
                # Link
                link_el = card.select_one("a[href]")
                if not link_el:
                    continue
                
                url = link_el.get("href", "")
                if not url.startswith("http"):
                    url = urljoin(self.BASE_URL, url)
                
                # Título
                title_el = card.select_one("h2, h3, .vehicle-title")
                title = title_el.get_text(strip=True) if title_el else ""
                
                # Preço
                price_el = card.select_one(".vehicle-price, .preco")
                price_text = price_el.get_text(strip=True) if price_el else ""
                
                # Ano
                year_el = card.select_one(".vehicle-year, .ano")
                year_text = year_el.get_text(strip=True) if year_el else ""
                
                # KM
                km_el = card.select_one(".vehicle-km, .km")
                km_text = km_el.get_text(strip=True) if km_el else ""
                
                # Localização
                location_el = card.select_one(".vehicle-location, .localizacao")
                location = location_el.get_text(strip=True) if location_el else ""
                
                # Imagem
                img_el = card.select_one("img")
                thumbnail = ""
                if img_el:
                    thumbnail = img_el.get("src") or img_el.get("data-src") or ""
                
                items.append({
                    "url": url,
                    "title": title,
                    "price": price_text,
                    "year": year_text,
                    "mileage": km_text,
                    "location": location,
                    "thumbnail": thumbnail,
                })
                
            except Exception:
                continue
        
        return items
    
    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normaliza dados de um anúncio."""
        try:
            url = raw_data.get("url", "")
            if not url or not url.startswith("http"):
                return None
            
            external_id = self._extract_id_from_url(url)
            if not external_id:
                return None
            
            title = raw_data.get("title", "").strip()
            price = self._parse_price(raw_data.get("price", ""))
            year = self._parse_year(raw_data.get("year", ""))
            mileage_km = self._parse_km(raw_data.get("mileage", ""))
            
            thumbnail = raw_data.get("thumbnail", "")
            if thumbnail and not thumbnail.startswith("http"):
                thumbnail = urljoin(self.BASE_URL, thumbnail)
            
            make, model = self._extract_make_model(title)
            
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
                "extractor_version": "chavesnamao_v1",
                "raw_payload": raw_data,
            }
            
        except Exception:
            return None
    
    # ========== Helpers ==========
    
    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrai ID do URL."""
        m = re.search(r'/(?:veiculo|anuncio)/(\d+)', url)
        if m:
            return m.group(1)
        
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()[:16]
    
    def _parse_price(self, s: str) -> Optional[Decimal]:
        """Parse preço."""
        if not s:
            return None
        
        s = s.replace("R$", "").strip()
        s = s.replace(".", "").replace(",", ".")
        s = re.sub(r'[^\d.]', '', s)
        
        try:
            return Decimal(s) if s else None
        except:
            return None
    
    def _parse_year(self, s: str) -> Optional[int]:
        """Parse ano."""
        if not s:
            return None
        
        m = re.search(r'(19\d{2}|20\d{2})', s)
        if m:
            year = int(m.group(1))
            return year if 1980 <= year <= 2030 else None
        return None
    
    def _parse_km(self, s: str) -> Optional[int]:
        """Parse km."""
        if not s:
            return None
        
        s = s.lower()
        if "mil" in s:
            m = re.search(r'(\d+)', s)
            if m:
                return int(m.group(1)) * 1000
        
        s = re.sub(r'[^\d]', '', s)
        return int(s) if s else None
    
    def _extract_make_model(self, title: str) -> tuple[Optional[str], Optional[str]]:
        """Extrai marca e modelo."""
        if not title:
            return None, None
        
        brands = ["honda", "toyota", "volkswagen", "ford", "chevrolet", "fiat"]
        title_lower = title.lower()
        
        for brand in brands:
            if brand in title_lower:
                make = brand.capitalize()
                idx = title_lower.find(brand)
                after = title[idx + len(brand):].strip()
                model = after.split()[0].capitalize() if after.split() else None
                return make, model
        
        return None, None
