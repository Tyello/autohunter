"""
Scraper para iCarros - HTTP-only, API pública.

Características:
- SSR tradicional (HTML server-side)
- API REST pública
- HTTP estável (baixo bloqueio)
- Parsing via BeautifulSoup
"""

from __future__ import annotations
from decimal import Decimal
from typing import Dict, Any, List, Optional
import re

from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin

from app.scrapers.scraper_base import BaseScraper


class ICarrosScraper(BaseScraper):
    """Scraper para iCarros (HTTP-only).
    
    URL base: https://www.icarros.com.br
    Método: HTTP + BeautifulSoup (SSR)
    """
    
    BASE_URL = "https://www.icarros.com.br"
    
    def __init__(self):
        super().__init__(source_name="icarros")
    
    def build_search_url(self, query: str, **kwargs) -> str:
        """Constrói URL de busca para iCarros.
        
        Formato: /carros/saopaulo?q=civic+si&ordenacao=relevancia
        
        Args:
            query: Termo de busca (ex: "civic si")
            **kwargs: location (default: "saopaulo")
        
        Returns:
            URL completa de busca
        """
        # Normaliza query
        q = quote_plus(query.strip())
        location = kwargs.get("location", "saopaulo")
        
        # URL base com localização
        url = f"{self.BASE_URL}/carros/{location}"
        
        # Adiciona query e ordenação
        url += f"?q={q}&ordenacao=relevancia"
        
        return url
    
    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        """Extrai cards de anúncios do HTML.
        
        iCarros usa class="carro-card" ou similar.
        """
        soup = BeautifulSoup(raw_content, "lxml")
        
        # iCarros pode usar diferentes classes dependendo da página
        # Tentamos vários seletores conhecidos
        cards = []
        
        # Seletor 1: cards principais
        cards = soup.select(".carro-card, .item-carro, .card-veiculo")
        
        if not cards:
            # Seletor 2: fallback para estrutura alternativa
            cards = soup.select("article[data-id]")
        
        if not cards:
            # Seletor 3: outro fallback
            cards = soup.select(".resultados-lista > li")
        
        items = []
        
        for card in cards:
            try:
                # Link principal
                link_el = card.select_one("a[href*='/anuncio/'], a.card-link, a.link-detalhes")
                if not link_el or not link_el.get("href"):
                    continue
                
                url = link_el.get("href", "")
                if not url.startswith("http"):
                    url = urljoin(self.BASE_URL, url)
                
                # Título
                title_el = card.select_one(
                    ".card-title, .titulo-anuncio, h2, h3, .nome-veiculo"
                )
                title = title_el.get_text(strip=True) if title_el else ""
                
                # Preço
                price_el = card.select_one(
                    ".card-price, .preco, .valor, [class*='preco']"
                )
                price_text = price_el.get_text(strip=True) if price_el else ""
                
                # Localização
                location_el = card.select_one(
                    ".card-location, .local, .localizacao, [class*='cidade']"
                )
                location = location_el.get_text(strip=True) if location_el else ""
                
                # Imagem/thumbnail
                img_el = card.select_one("img")
                thumbnail = img_el.get("src") or img_el.get("data-src") if img_el else ""
                
                # Quilometragem
                km_el = card.select_one(
                    ".card-km, .km, .quilometragem, [class*='km']"
                )
                km_text = km_el.get_text(strip=True) if km_el else ""
                
                # Ano
                year_el = card.select_one(
                    ".card-year, .ano, [class*='ano']"
                )
                year_text = year_el.get_text(strip=True) if year_el else ""
                
                # Transmissão
                trans_el = card.select_one(
                    ".transmissao, .cambio, [class*='transmis']"
                )
                trans_text = trans_el.get_text(strip=True) if trans_el else ""
                
                # Combustível
                fuel_el = card.select_one(
                    ".combustivel, [class*='combustivel']"
                )
                fuel_text = fuel_el.get_text(strip=True) if fuel_el else ""
                
                items.append({
                    "url": url,
                    "title": title,
                    "price": price_text,
                    "location": location,
                    "thumbnail": thumbnail,
                    "mileage": km_text,
                    "year": year_text,
                    "transmission": trans_text,
                    "fuel": fuel_text,
                })
                
            except Exception as e:
                # Log mas não quebra pipeline
                continue
        
        return items
    
    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normaliza dados de um anúncio do iCarros.
        
        Args:
            raw_data: Dict com dados brutos extraídos
        
        Returns:
            Dict normalizado ou None se inválido
        """
        try:
            url = raw_data.get("url", "")
            if not url or not url.startswith("http"):
                return None
            
            # External ID: extrai do URL
            external_id = self._extract_id_from_url(url)
            if not external_id:
                return None
            
            # Parse campos
            title = raw_data.get("title", "").strip()
            
            price = self._parse_price(raw_data.get("price", ""))
            year = self._parse_year(raw_data.get("year", ""))
            mileage_km = self._parse_km(raw_data.get("mileage", ""))
            
            # Normaliza thumbnail (pode vir lazy-load)
            thumbnail = raw_data.get("thumbnail", "")
            if thumbnail and not thumbnail.startswith("http"):
                thumbnail = urljoin(self.BASE_URL, thumbnail)
            
            # Extrai marca e modelo do título (heurística)
            make, model = self._extract_make_model(title)
            
            # Normaliza transmissão
            transmission = self._normalize_transmission(
                raw_data.get("transmission", "")
            )
            
            # Normaliza combustível
            fuel_type = self._normalize_fuel(
                raw_data.get("fuel", "")
            )
            
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
                "extractor_version": "icarros_v1",
                "extras": {
                    "raw_transmission": raw_data.get("transmission", ""),
                    "raw_fuel": raw_data.get("fuel", ""),
                },
                "raw_payload": raw_data,
            }
            
        except Exception as e:
            return None
    
    # ========== Helper Methods ==========
    
    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrai ID do anúncio do URL.
        
        Exemplos:
        - /anuncio/123456 → "123456"
        - /anuncios/honda-civic/123456 → "123456"
        """
        # Tenta padrão /anuncio/ID
        m = re.search(r'/anuncios?/(?:[^/]+/)*(\d+)', url)
        if m:
            return m.group(1)
        
        # Fallback: hash do URL
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()[:16]
    
    def _parse_price(self, s: str) -> Optional[Decimal]:
        """Parse preço BRL.
        
        Exemplos:
        - "R$ 50.000" → 50000
        - "50000" → 50000
        - "R$ 50.000,00" → 50000
        """
        if not s:
            return None
        
        # Remove símbolos e espaços
        s = s.replace("R$", "").replace("$", "").strip()
        
        # Remove pontos (milhares) e troca vírgula por ponto (decimal)
        s = s.replace(".", "").replace(",", ".")
        
        # Remove não-dígitos exceto ponto
        s = re.sub(r'[^\d.]', '', s)
        
        if not s:
            return None
        
        try:
            return Decimal(s)
        except:
            return None
    
    def _parse_year(self, s: str) -> Optional[int]:
        """Extrai ano (ex: '2019' ou '2019/2020').
        
        Se tiver 2 anos (ex: 2019/2020), pega o primeiro (ano fabricação).
        """
        if not s:
            return None
        
        # Busca primeiro ano de 4 dígitos
        m = re.search(r'(19\d{2}|20\d{2})', s)
        if m:
            try:
                year = int(m.group(1))
                # Validação razoável
                if 1980 <= year <= 2030:
                    return year
            except:
                pass
        
        return None
    
    def _parse_km(self, s: str) -> Optional[int]:
        """Parse quilometragem.
        
        Exemplos:
        - "50.000 km" → 50000
        - "50000km" → 50000
        - "50 mil km" → 50000
        """
        if not s:
            return None
        
        s = s.lower()
        
        # Trata "mil" (ex: "50 mil km" → "50000")
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
        """Extrai marca e modelo do título (heurística).
        
        Exemplo:
        - "Honda Civic SI 2019" → ("Honda", "Civic")
        - "Volkswagen Gol 1.0" → ("Volkswagen", "Gol")
        """
        if not title:
            return None, None
        
        # Marcas conhecidas (primeiro nível)
        brands = [
            "honda", "toyota", "volkswagen", "vw", "ford", "chevrolet", 
            "fiat", "hyundai", "nissan", "renault", "peugeot", "citroën",
            "jeep", "bmw", "mercedes", "audi", "volvo", "mitsubishi",
            "suzuki", "kia", "chery", "caoa", "ram"
        ]
        
        title_lower = title.lower()
        
        # Busca marca
        make = None
        matched_brand = None
        for brand in brands:
            if re.search(rf"\b{re.escape(brand)}\b", title_lower):
                make = brand.capitalize()
                matched_brand = brand
                if brand == "vw":
                    make = "Volkswagen"
                break
        
        # Extrai modelo (primeira palavra após marca)
        if make:
            # Acha posição da marca no título
            idx = title_lower.find((matched_brand or make).lower())
            if idx >= 0:
                # Pega palavras após marca
                after = title[idx + len(matched_brand or make):].strip()
                words = after.split()
                if words:
                    # Modelo é primeira palavra
                    model = words[0].capitalize()
                    return make, model
        
        return make, None
    
    def _normalize_transmission(self, s: str) -> Optional[str]:
        """Normaliza tipo de transmissão.
        
        Returns:
            "manual" | "automatic" | None
        """
        if not s:
            return None
        
        s = s.lower()
        
        if "manual" in s or "mecânica" in s or "mecanic" in s:
            return "manual"
        
        if "automát" in s or "auto" in s or "cvt" in s or "dct" in s:
            return "automatic"
        
        return None
    
    def _normalize_fuel(self, s: str) -> Optional[str]:
        """Normaliza tipo de combustível.
        
        Returns:
            "gasoline" | "ethanol" | "flex" | "diesel" | "electric" | "hybrid" | None
        """
        if not s:
            return None
        
        s = s.lower()
        
        if "flex" in s or "flexível" in s:
            return "flex"
        
        if "gasolina" in s or "gasoline" in s:
            return "gasoline"
        
        if "etanol" in s or "álcool" in s or "alcool" in s:
            return "ethanol"
        
        if "diesel" in s or "óleo" in s:
            return "diesel"
        
        if "elétric" in s or "electric" in s or "ev" in s:
            return "electric"
        
        if "híbrid" in s or "hybrid" in s:
            return "hybrid"
        
        return None
