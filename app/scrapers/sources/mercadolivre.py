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

from urllib.parse import quote_plus, urlparse

from app.scrapers.scraper_base import BaseScraper


class MercadoLivreScraper(BaseScraper):
    """Scraper para Mercado Livre (API JSON)."""

    BASE_URL = "https://api.mercadolibre.com/sites/MLB/search"

    def __init__(self):
        super().__init__(source_name="mercadolivre")

    def build_search_url(self, query: str, **kwargs) -> str:
        """Constrói URL da API de busca para veículos (categoria MLB1743)."""
        q = quote_plus(query.strip())
        return f"{self.BASE_URL}?q={q}&category=MLB1743"

    def extract_raw_data(self, raw_content: str, ctx) -> List[Dict]:
        """Extrai anúncios a partir de resposta JSON da API do Mercado Livre."""
        try:
            payload = json.loads(raw_content)
        except json.JSONDecodeError:
            return []

        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            return []

        items: List[Dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue

            url = str(item.get("permalink") or "").strip()
            if not url:
                continue

            if self._is_tracking_url(url) or not self._is_vehicle_listing(url):
                continue

            items.append(item)

        return items

    def parse_listing(self, raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normaliza dados de um anúncio da API do Mercado Livre."""
        try:
            external_id = str(raw_data.get("id") or "").strip()
            if not external_id:
                return None

            url = self._clean_url(str(raw_data.get("permalink") or "").strip())
            if not url or not url.startswith("http"):
                return None

            if self._is_tracking_url(url) or not self._is_vehicle_listing(url):
                return None

            title = str(raw_data.get("title") or "").strip()
            if not title:
                return None

            price = self._parse_price(str(raw_data.get("price") or ""))
            currency = str(raw_data.get("currency_id") or "").strip() or None

            thumbnail = str(raw_data.get("thumbnail") or "").strip() or None
            if thumbnail and thumbnail.startswith("http://"):
                thumbnail = thumbnail.replace("http://", "https://", 1)

            location_obj = raw_data.get("location") if isinstance(raw_data.get("location"), dict) else {}
            city = ((location_obj.get("city") or {}).get("name") or "").strip()
            state = ((location_obj.get("state") or {}).get("name") or "").strip()
            location = ", ".join([x for x in [city, state] if x]) or None

            attributes = raw_data.get("attributes") if isinstance(raw_data.get("attributes"), list) else []

            year = self._parse_year(self._extract_attribute(attributes, "VEHICLE_YEAR"))
            if year is None:
                year = self._extract_year_from_title(title)

            mileage_km = self._parse_km(self._extract_attribute(attributes, "KILOMETERS") or "")

            make = self._extract_attribute(attributes, "BRAND")
            model = self._extract_attribute(attributes, "MODEL")
            if not make or not model:
                parsed_make, parsed_model = self._extract_make_model(title)
                make = make or parsed_make
                model = model or parsed_model

            fuel_type = self._normalize_fuel(self._extract_attribute(attributes, "FUEL_TYPE") or "")
            transmission = self._normalize_transmission(self._extract_attribute(attributes, "TRANSMISSION") or "")

            seller = raw_data.get("seller") if isinstance(raw_data.get("seller"), dict) else {}

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
                    "attributes": attributes,
                    "seller_id": seller.get("id"),
                    "condition": raw_data.get("condition"),
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

            return host in {
                "carro.mercadolivre.com.br",
                "moto.mercadolivre.com.br",
            }
        except Exception:
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

        except Exception:
            pass

        return False

    def _clean_url(self, url: str) -> str:
        """Remove query params."""
        if not url:
            return ""

        try:
            parsed = urlparse(url)
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            return clean
        except Exception:
            return url.split("?")[0].split("#")[0]

    def _extract_id_from_url(self, url: str) -> Optional[str]:
        """Extrai ID MLB do URL."""
        if not url:
            return None

        m = re.search(r"MLB-?(\d+)", url, re.I)
        if m:
            return f"MLB{m.group(1)}"

        return None

    def _extract_attribute(self, attributes: List[Dict[str, Any]], attribute_id: str) -> Optional[str]:
        """Extrai value_name de um atributo pelo id."""
        if not attributes or not attribute_id:
            return None

        target = attribute_id.upper()
        for item in attributes:
            if not isinstance(item, dict):
                continue

            if str(item.get("id") or "").upper() == target:
                value = item.get("value_name")
                if value is None:
                    return None
                value_s = str(value).strip()
                return value_s or None

        return None

    def _parse_year(self, value: Any) -> Optional[int]:
        """Converte ano textual/numérico em int válido."""
        if value is None:
            return None

        if isinstance(value, int):
            year = value
        else:
            m = re.search(r"\b(19\d{2}|20\d{2})\b", str(value))
            if not m:
                return None
            year = int(m.group(1))

        if 1980 <= year <= 2030:
            return year
        return None

    def _parse_price(self, s: str) -> Optional[Decimal]:
        """Parse preço."""
        if not s:
            return None

        s = s.replace("R$", "").replace("$", "").strip()
        s = s.replace(".", "").replace(",", ".")
        s = re.sub(r"[^\d.]", "", s)

        if not s:
            return None

        try:
            return Decimal(s)
        except Exception:
            return None

    def _extract_year_from_title(self, title: str) -> Optional[int]:
        """Extrai ano do título."""
        if not title:
            return None

        m = re.search(r"\b(19\d{2}|20\d{2})\b", title)
        if m:
            try:
                year = int(m.group(1))
                if 1980 <= year <= 2030:
                    return year
            except Exception:
                pass

        return None

    def _parse_km(self, s: str) -> Optional[int]:
        """Parse km."""
        if not s:
            return None

        s = s.lower()

        if "mil" in s:
            m = re.search(r"(\d+(?:[,.]\d+)?)\s*mil", s)
            if m:
                try:
                    num = float(m.group(1).replace(",", "."))
                    return int(num * 1000)
                except Exception:
                    pass

        s = re.sub(r"[^\d]", "", s)

        if not s:
            return None

        try:
            return int(s)
        except Exception:
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
        matched_brand = None
        for brand in brands:
            if re.search(rf"\b{re.escape(brand)}\b", title_lower):
                make = brand.capitalize()
                matched_brand = brand
                if brand == "vw":
                    make = "Volkswagen"
                break

        if make:
            idx = title_lower.find((matched_brand or make).lower())
            if idx >= 0:
                after = title[idx + len(matched_brand or make):].strip()
                words = after.split()
                if words:
                    model = words[0].capitalize()
                    return make, model

        return make, None

    def _normalize_fuel(self, s: str) -> Optional[str]:
        """Normaliza combustível para enum canônico."""
        if not s:
            return None

        s = s.lower()
        if "flex" in s:
            return "flex"
        if "gasolina" in s or "nafta" in s or "gasoline" in s:
            return "gasoline"
        if "etanol" in s or "álcool" in s or "alcool" in s:
            return "ethanol"
        if "diesel" in s:
            return "diesel"
        if "elétric" in s or "electric" in s or "ev" in s:
            return "electric"
        if "híbrid" in s or "hybrid" in s:
            return "hybrid"
        return None

    def _normalize_transmission(self, s: str) -> Optional[str]:
        """Normaliza transmissão para enum canônico."""
        if not s:
            return None

        s = s.lower()
        if "manual" in s or "mecânica" in s or "mecanic" in s:
            return "manual"
        if "automát" in s or "auto" in s or "cvt" in s or "dct" in s:
            return "automatic"
        return None
