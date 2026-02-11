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

from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin, urlparse

from app.scrapers.scraper_base import BaseScraper


class MercadoLivreScraper(BaseScraper):
    """Scraper para Mercado Livre - CORRIGIDO (HTML)."""

    BASE_URL = "https://lista.mercadolivre.com.br"
    VEHICLES_PREFIX = "/veiculos/carros-caminhonetes/"

    def __init__(self):
        super().__init__(source_name="mercadolivre")

    def build_search_url(self, query: str, **kwargs) -> str:
        """Constrói URL de busca.

        Formato ML: /Honda-Civic
        ou: /carros-motos/carros-caminhonetes/honda/civic
        """
        # Normaliza query para um slug estável.
        # Ex.: "Civic SI" -> "civic-si"
        raw = (query or "").strip().lower()
        raw = re.sub(r"[^\w\s-]+", " ", raw, flags=re.UNICODE)
        slug = re.sub(r"[\s_]+", "-", raw).strip("-")
        if not slug:
            slug = "carro"

        # Mercado Livre canonicaliza veículos nesse vertical.
        return f"{self.BASE_URL}{self.VEHICLES_PREFIX}{slug}"

    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        """Extrai anúncios do HTML do site."""
        soup = BeautifulSoup(raw_content, "lxml")

        items = []

        # Mercado Livre usa diferentes estruturas
        # Seletores conhecidos (2024-2026):
        cards = (
                soup.select("li.ui-search-layout__item") or
                soup.select("div.ui-search-result") or
                soup.select("div[class*='item__container']") or
                soup.select("article") or
                soup.select("li:has(a[href*='MLB-'])")
        )

        for card in cards:
            try:
                # Link do anúncio
                link_el = (
                        card.select_one("a[href*='MLB-']") or
                        card.select_one("a.ui-search-link") or
                        card.select_one("a[href]")
                )

                if not link_el:
                    continue

                url = link_el.get("href", "")
                if not url:
                    continue

                # Limpa URL (remove tracking)
                url = self._clean_url(url)

                # Skip se não é veículo
                if not self._is_vehicle_listing(url):
                    continue

                # Skip tracking URLs
                if self._is_tracking_url(url):
                    continue

                # ID do anúncio
                item_id = self._extract_id_from_url(url)
                if not item_id:
                    continue

                # Título
                title_el = (
                        card.select_one("h2") or
                        card.select_one(".ui-search-item__title") or
                        card.select_one("a[title]")
                )
                title = ""
                if title_el:
                    title = title_el.get_text(strip=True) or title_el.get("title", "")

                # Preço
                price_el = (
                        card.select_one(".price-tag-fraction") or
                        card.select_one(".ui-search-price__second-line") or
                        card.select_one("span[class*='price']")
                )
                price_text = price_el.get_text(strip=True) if price_el else ""

                # Imagem
                img_el = card.select_one("img")
                thumbnail = ""
                if img_el:
                    thumbnail = (
                                        img_el.get("data-src") or
                                        img_el.get("src") or
                                        img_el.get("data-lazy")
                                ) or ""

                # Localização
                location_el = card.select_one(".ui-search-item__location, .ui-search-item__location-label")
                location = location_el.get_text(strip=True) if location_el else ""

                # Atributos (ano, km, etc)
                attrs = []
                attr_els = card.select(".ui-search-item__attribute, li[class*='attribute']")
                for el in attr_els:
                    attrs.append(el.get_text(strip=True))

                items.append({
                    "id": item_id,
                    "url": url,
                    "title": title,
                    "price": price_text,
                    "thumbnail": thumbnail,
                    "location": location,
                    "attributes": attrs,
                })

            except Exception:
                continue

        return items

    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normaliza dados de um anúncio."""
        try:
            # ID e URL
            external_id = str(raw_data.get("id") or "")
            if not external_id:
                return None

            url = raw_data.get("url", "")
            if not url or not url.startswith("http"):
                return None

            # Título
            title = raw_data.get("title", "").strip()
            if not title:
                return None

            # Preço
            price = self._parse_price(raw_data.get("price", ""))

            # Thumbnail
            thumbnail = raw_data.get("thumbnail", "")
            if thumbnail and thumbnail.startswith("http://"):
                thumbnail = thumbnail.replace("http://", "https://")

            # Localização
            location = raw_data.get("location", "").strip() or None

            # Extrai informações do título e atributos
            year = self._extract_year_from_title(title)
            make, model = self._extract_make_model(title)

            # Atributos
            attributes = raw_data.get("attributes", [])
            mileage_km = self._extract_km_from_attrs(attributes)

            return {
                "external_id": external_id,
                "title": title,
                "url": url,
                "thumbnail_url": thumbnail or None,
                "price": price,
                "location": location,
                "year": year,
                "mileage_km": mileage_km,
                "make": make,
                "model": model,
                "extractor_version": "mercadolivre_v2_html",
                "extras": {
                    "attributes": attributes,
                },
                "raw_payload": raw_data,
            }

        except Exception:
            return None

    # ========== Helper Methods ==========

    def _is_vehicle_listing(self, url: str) -> bool:
        """Verifica se é anúncio de veículo."""
        if not url:
            return False

        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower()

            # Restringe para hosts do vertical de veículos.
            # Importante: muitas páginas de produtos também têm "MLB" na URL;
            # por isso NÃO aceitamos MLB como sinal de veículo.
            vehicle_hosts = {
                "carro.mercadolivre.com.br",
                "moto.mercadolivre.com.br",
            }
            if host in vehicle_hosts:
                return True

            return False

        except:
            return False

    def _is_tracking_url(self, url: str) -> bool:
        """Detecta URLs de tracking."""
        if not url:
            return False

        try:
            parsed = urlparse(url)
            host = parsed.netloc.lower()
            path = parsed.path.lower()

            if host.startswith("click") or host.startswith("clk"):
                return True

            if "brand_ads" in path or "/ads/" in path:
                return True

        except:
            pass

        return False

    def _clean_url(self, url: str) -> str:
        """Remove query params."""
        if not url:
            return ""

        # completa esquema e normaliza URLs relativas
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = urljoin("https://www.mercadolivre.com.br", url)
        elif not re.match(r"^https?://", url, re.I):
            # Ex.: "carro.mercadolivre.com.br/MLB-..."
            if "mercadolivre.com.br" in url:
                url = "https://" + url.lstrip("/")

        try:
            parsed = urlparse(url)
            scheme = parsed.scheme or "https"
            clean = f"{scheme}://{parsed.netloc}{parsed.path}"
            return clean
        except Exception:
            return url.split("?")[0].split("#")[0]

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrai ID MLB do URL."""
        if not url:
            return None

        # Formato: MLB-123456789 ou MLB123456789
        m = re.search(r'MLB-?(\d+)', url, re.I)
        if m:
            return f"MLB{m.group(1)}"

        return None

    def _parse_price(self, s: str) -> Optional[Decimal]:
        """Parse preço."""
        if not s:
            return None

        # ML usa formato: "50.000" ou "50000"
        s = s.replace("R$", "").replace("$", "").strip()
        s = s.replace(".", "").replace(",", ".")
        s = re.sub(r'[^\d.]', '', s)

        if not s:
            return None

        try:
            return Decimal(s)
        except:
            return None

    def _extract_year_from_title(self, title: str) -> Optional[int]:
        """Extrai ano do título."""
        if not title:
            return None

        # Procura 4 dígitos
        m = re.search(r'\b(19\d{2}|20\d{2})\b', title)
        if m:
            try:
                year = int(m.group(1))
                if 1980 <= year <= 2030:
                    return year
            except:
                pass

        return None

    def _extract_km_from_attrs(self, attrs: List[str]) -> Optional[int]:
        """Extrai km dos atributos."""
        if not attrs:
            return None

        for attr in attrs:
            # Procura por km
            if re.search(r'\d+.*km', attr, re.I):
                return self._parse_km(attr)

        return None

    def _parse_km(self, s: str) -> Optional[int]:
        """Parse km."""
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
