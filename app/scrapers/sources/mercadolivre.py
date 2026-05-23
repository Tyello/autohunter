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
import time

from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin, urlparse

from app.scrapers.scraper_base import BaseScraper
from app.scrapers.scraper_base.fetcher import FetchResult
from app.scrapers.base import FetchBlocked
from app.scrapers.mercadolivre import (
    _fetch_ml_search_with_shell_fallback,
    _is_ml_shell_without_results,
    _parse_polycard_items,
)


class MercadoLivreScraper(BaseScraper):
    """Scraper para Mercado Livre.

    Mantém compatibilidade com payload antigo da API (JSON) e com parsing HTML.
    """

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

        return f"{self.BASE_URL}{self.VEHICLES_PREFIX}{slug}"

    def build_api_search_url(self, query: str) -> str:
        """Mantém endpoint da API pública para compatibilidade/fallback explícito."""
        return (
            "https://api.mercadolibre.com/sites/MLB/search"
            f"?q={quote_plus(query or '')}&category=MLB1743"
        )

    def _fetch_content(self, search_url: str, ctx):
        """Fetch V2 alinhado ao V1: HTML + fallback browser networkidle."""
        is_ml_html_listing = (
            isinstance(search_url, str)
            and "lista.mercadolivre.com.br/veiculos/carros-caminhonetes/" in search_url
        )
        if not is_ml_html_listing:
            return super()._fetch_content(search_url, ctx)

        try:
            started = time.time()
            html = _fetch_ml_search_with_shell_fallback(search_url, ctx)
            if _is_ml_shell_without_results(html):
                raise FetchBlocked(403, search_url, reason="ml_shell_without_results")
            return FetchResult(
                content=html,
                final_url=search_url,
                method="browser_fallback",
                duration_ms=int((time.time() - started) * 1000),
            )
        except FetchBlocked:
            raise
        except Exception as exc:
            raise FetchBlocked(403, search_url, reason=f"ml_v2_fetch_error:{exc}") from exc

    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        """Extrai anúncios de JSON (API) ou HTML (fallback)."""
        try:
            payload = json.loads(raw_content or "")
        except Exception:
            payload = None

        if isinstance(payload, dict) and isinstance(payload.get("results"), list):
            out: list[dict] = []
            for item in payload.get("results", []):
                if not isinstance(item, dict):
                    continue
                url = self._clean_url(item.get("permalink") or item.get("url") or "")
                if not url or self._is_tracking_url(url) or not self._is_vehicle_listing(url):
                    continue
                out.append({**item, "permalink": url, "url": url})
            return out

        soup = BeautifulSoup(raw_content, "lxml")
        items: list[dict] = []
        seen_ids: set[str] = set()

        poly_items = _parse_polycard_items(raw_content or "", limit=50)
        for poly in poly_items:
            converted = self._convert_polycard_item(poly)
            if not converted:
                continue
            item_id = str(converted.get("id") or "")
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            items.append(converted)

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
                if not title:
                    title = self._extract_title_from_card_fallback(card, link_el, url)

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

                item = {
                    "id": item_id,
                    "url": url,
                    "permalink": url,
                    "title": title,
                    "price": price_text,
                    "thumbnail": thumbnail,
                    "location": location,
                    "attributes": attrs,
                }
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                items.append(item)

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

            url = raw_data.get("permalink") or raw_data.get("url", "")
            if not url or not url.startswith("http"):
                return None
            if self._is_tracking_url(url):
                return None
            url = self._clean_url(url)

            # Título
            title = raw_data.get("title", "").strip()
            if not title:
                title = self._title_from_listing_url(url)
            if not title:
                return None

            # Preço
            price = self._parse_price(raw_data.get("price", ""))

            # Thumbnail
            thumbnail = raw_data.get("thumbnail", "")
            if thumbnail and thumbnail.startswith("http://"):
                thumbnail = thumbnail.replace("http://", "https://")

            # Localização
            location_raw = raw_data.get("location")
            location = location_raw.strip() if isinstance(location_raw, str) else None

            attributes = raw_data.get("attributes", [])
            year = self._parse_year(self._extract_attribute(attributes, "VEHICLE_YEAR")) or self._extract_year_from_title(title)
            make = self._extract_attribute(attributes, "BRAND")
            model = self._extract_attribute(attributes, "MODEL")
            if not make or not model:
                t_make, t_model = self._extract_make_model(title)
                make = make or t_make
                model = model or t_model
            mileage_km = self._parse_km(self._extract_attribute(attributes, "KILOMETERS") or "")
            if mileage_km is None and isinstance(attributes, list):
                mileage_km = self._extract_km_from_attrs([a for a in attributes if isinstance(a, str)])
            fuel_type = self._normalize_fuel(self._extract_attribute(attributes, "FUEL_TYPE") or "")
            transmission = self._normalize_transmission(self._extract_attribute(attributes, "TRANSMISSION") or "")

            location_obj = raw_data.get("location") or {}
            if isinstance(location_obj, dict):
                city = ((location_obj.get("city") or {}).get("name") or "").strip()
                state = ((location_obj.get("state") or {}).get("name") or "").strip()
                if city and state:
                    location = f"{city}, {state}"

            return {
                "external_id": external_id,
                "title": title,
                "url": url,
                "thumbnail_url": thumbnail or None,
                "price": price,
                "currency": raw_data.get("currency_id") or "BRL",
                "location": location,
                "year": year,
                "mileage_km": mileage_km,
                "make": make,
                "model": model,
                "fuel_type": fuel_type,
                "transmission": transmission,
                "extractor_version": "mercadolivre_v1",
                "extras": {
                    "attributes": attributes,
                    "seller_id": (raw_data.get("seller") or {}).get("id"),
                },
                "raw_payload": raw_data,
            }

        except Exception:
            return None

    def _convert_polycard_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(item, dict):
            return None
        url = self._clean_url(item.get("url") or "")
        external_id = str(item.get("external_id") or "")
        if not external_id or not url or not self._is_vehicle_listing(url):
            return None
        title = str(item.get("title") or "").strip() or self._title_from_listing_url(url)
        return {
            "id": external_id,
            "title": title,
            "url": url,
            "permalink": url,
            "thumbnail": item.get("thumbnail_url") or "",
            "price": item.get("price"),
            "currency_id": item.get("currency") or "BRL",
            "location": item.get("location") or "",
            "attributes": [],
        }

    def _extract_title_from_card_fallback(self, card, link_el, url: str) -> str:
        img_el = card.select_one("img")
        if img_el:
            for key in ("alt", "title"):
                value = (img_el.get(key) or "").strip()
                if value:
                    return value
        for key in ("title", "aria-label"):
            value = (link_el.get(key) or "").strip()
            if value:
                return value
        return self._title_from_listing_url(url)

    def _title_from_listing_url(self, url: str) -> str:
        if not url:
            return ""
        parsed = urlparse(url)
        slug = (parsed.path or "").split("/")[-1]
        slug = re.sub(r"^MLB-?\d+-?", "", slug, flags=re.I)
        slug = re.sub(r"[-_]+JM$", "", slug, flags=re.I)
        slug = slug.replace("-", " ").replace("_", " ").strip()
        if not slug:
            return ""
        return re.sub(r"\s+", " ", slug).title()

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

    def _extract_attribute(self, attributes: List[Dict[str, Any]], attr_id: str) -> Optional[str]:
        for attr in attributes or []:
            if not isinstance(attr, dict):
                continue
            if str(attr.get("id") or "").upper() == str(attr_id or "").upper():
                value = attr.get("value_name")
                if value is not None:
                    return str(value)
        return None

    def _parse_year(self, v: Any) -> Optional[int]:
        try:
            y = int(v)
        except Exception:
            return None
        return y if 1900 <= y <= 2100 else None

    def _normalize_fuel(self, v: str) -> Optional[str]:
        s = (v or "").strip().lower()
        if not s:
            return None
        if "flex" in s:
            return "flex"
        if "diesel" in s:
            return "diesel"
        if "ele" in s or "elétr" in s or "eletr" in s:
            return "electric"
        if s in {"nafta", "gasolina", "gasoline"}:
            return "gasoline"
        return s

    def _normalize_transmission(self, v: str) -> Optional[str]:
        s = (v or "").strip().lower()
        if not s:
            return None
        if "manual" in s:
            return "manual"
        if "auto" in s or "cvt" in s:
            return "automatic"
        return s

    def _parse_price(self, s: Any) -> Optional[Decimal]:
        """Parse preço."""
        if s is None or s == "":
            return None

        if isinstance(s, (int, float, Decimal)):
            try:
                return Decimal(str(s))
            except Exception:
                return None

        s = str(s)
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
