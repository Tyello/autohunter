"""
Scrapers Browser-Required: GoGarage e Mobiauto.

Ambos requerem browser por serem SPAs com proteção anti-bot.
Implementações simplificadas compartilhando lógica comum.
"""

from __future__ import annotations
from decimal import Decimal
from typing import Dict, Any, List, Optional
import re

from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

from app.scrapers.scraper_base import BaseScraper


class GoGarageScraper(BaseScraper):
    """Scraper para GoGarage (Browser Required - SPA Vue)."""
    
    BASE_URL = "https://www.gogarage.com.br"
    
    def __init__(self):
        super().__init__(source_name="gogarage")
    
    def build_search_url(self, query: str, **kwargs) -> str:
        q = query.replace(" ", "-").lower()
        return f"{self.BASE_URL}/carros/{q}"
    
    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        soup = BeautifulSoup(raw_content, "lxml")
        items = []
        
        cards = soup.select(".vehicle-card, article[data-vehicle]")
        
        for card in cards:
            try:
                link = card.select_one("a[href]")
                if not link:
                    continue
                
                url = link.get("href", "")
                if not url.startswith("http"):
                    url = urljoin(self.BASE_URL, url)
                
                title = card.select_one("h2, h3")
                price = card.select_one(".price")
                year = card.select_one(".year")
                km = card.select_one(".km")
                img = card.select_one("img")
                
                items.append({
                    "url": url,
                    "title": title.get_text(strip=True) if title else "",
                    "price": price.get_text(strip=True) if price else "",
                    "year": year.get_text(strip=True) if year else "",
                    "mileage": km.get_text(strip=True) if km else "",
                    "thumbnail": img.get("src") if img else "",
                })
            except:
                continue
        
        return items
    
    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = raw_data.get("url", "")
        if not url:
            return None
        
        import hashlib
        external_id = hashlib.md5(url.encode()).hexdigest()[:16]
        
        title = raw_data.get("title", "").strip()
        price_str = raw_data.get("price", "")
        price = self._parse_price(price_str)
        year = self._parse_year(raw_data.get("year", ""))
        km = self._parse_km(raw_data.get("mileage", ""))
        
        make, model = self._extract_make_model(title)
        
        return {
            "external_id": external_id,
            "title": title,
            "url": url,
            "thumbnail_url": raw_data.get("thumbnail") or None,
            "price": price,
            "year": year,
            "mileage_km": km,
            "make": make,
            "model": model,
            "extractor_version": "gogarage_v1",
            "raw_payload": raw_data,
        }
    
    def _parse_price(self, s: str) -> Optional[Decimal]:
        if not s:
            return None
        s = re.sub(r'[^\d]', '', s.replace(".", "").replace(",", "."))
        try:
            return Decimal(s) if s else None
        except:
            return None
    
    def _parse_year(self, s: str) -> Optional[int]:
        m = re.search(r'(20\d{2})', s)
        return int(m.group(1)) if m else None
    
    def _parse_km(self, s: str) -> Optional[int]:
        if not s:
            return None
        if "mil" in s.lower():
            m = re.search(r'(\d+)', s)
            return int(m.group(1)) * 1000 if m else None
        s = re.sub(r'[^\d]', '', s)
        return int(s) if s else None
    
    def _extract_make_model(self, title: str) -> tuple[Optional[str], Optional[str]]:
        if not title:
            return None, None
        brands = ["honda", "toyota", "ford", "chevrolet", "fiat"]
        for brand in brands:
            if brand in title.lower():
                idx = title.lower().find(brand)
                make = brand.capitalize()
                after = title[idx+len(brand):].strip().split()
                model = after[0].capitalize() if after else None
                return make, model
        return None, None


class MobiautoScraper(BaseScraper):
    """Scraper para Mobiauto (Browser Required - proteção anti-bot)."""
    
    BASE_URL = "https://www.mobiauto.com.br"
    
    def __init__(self):
        super().__init__(source_name="mobiauto")
    
    def build_search_url(self, query: str, **kwargs) -> str:
        q = quote_plus(query)
        return f"{self.BASE_URL}/busca?q={q}"
    
    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        soup = BeautifulSoup(raw_content, "lxml")
        items = []
        
        cards = soup.select(".card-vehicle, article.vehicle")
        
        for card in cards:
            try:
                link = card.select_one("a")
                if not link:
                    continue
                
                url = link.get("href", "")
                if not url.startswith("http"):
                    url = urljoin(self.BASE_URL, url)
                
                title = card.select_one("h2, h3")
                price = card.select_one(".price")
                year = card.select_one(".year")
                km = card.select_one(".km")
                img = card.select_one("img")
                
                items.append({
                    "url": url,
                    "title": title.get_text(strip=True) if title else "",
                    "price": price.get_text(strip=True) if price else "",
                    "year": year.get_text(strip=True) if year else "",
                    "mileage": km.get_text(strip=True) if km else "",
                    "thumbnail": img.get("src") if img else "",
                })
            except:
                continue
        
        return items
    
    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = raw_data.get("url", "")
        if not url:
            return None
        
        import hashlib
        external_id = hashlib.md5(url.encode()).hexdigest()[:16]
        
        title = raw_data.get("title", "").strip()
        price = self._parse_price(raw_data.get("price", ""))
        year = self._parse_year(raw_data.get("year", ""))
        km = self._parse_km(raw_data.get("mileage", ""))
        
        make, model = self._extract_make_model(title)
        
        return {
            "external_id": external_id,
            "title": title,
            "url": url,
            "thumbnail_url": raw_data.get("thumbnail") or None,
            "price": price,
            "year": year,
            "mileage_km": km,
            "make": make,
            "model": model,
            "extractor_version": "mobiauto_v1",
            "raw_payload": raw_data,
        }
    
    def _parse_price(self, s: str) -> Optional[Decimal]:
        if not s:
            return None
        s = re.sub(r'[^\d]', '', s.replace(".", "").replace(",", "."))
        try:
            return Decimal(s) if s else None
        except:
            return None
    
    def _parse_year(self, s: str) -> Optional[int]:
        m = re.search(r'(20\d{2})', s)
        return int(m.group(1)) if m else None
    
    def _parse_km(self, s: str) -> Optional[int]:
        if not s:
            return None
        if "mil" in s.lower():
            m = re.search(r'(\d+)', s)
            return int(m.group(1)) * 1000 if m else None
        s = re.sub(r'[^\d]', '', s)
        return int(s) if s else None
    
    def _extract_make_model(self, title: str) -> tuple[Optional[str], Optional[str]]:
        if not title:
            return None, None
        brands = ["honda", "toyota", "ford", "chevrolet", "fiat", "volkswagen"]
        for brand in brands:
            if brand in title.lower():
                idx = title.lower().find(brand)
                make = brand.capitalize()
                if brand == "volkswagen":
                    make = "Volkswagen"
                after = title[idx+len(brand):].strip().split()
                model = after[0].capitalize() if after else None
                return make, model
        return None, None
