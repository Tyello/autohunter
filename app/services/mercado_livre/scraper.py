# app/services/mercado_livre/scraper.py
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import hashlib


class MercadoLivreScraper:
    BASE_URL = "https://lista.mercadolivre.com.br/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/123.0.0.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9",
        })

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Realiza busca e retorna lista de anúncios formatados para ingest."""
        query_url = f"{self.BASE_URL}{query.replace(' ', '-')}"
        response = self.session.get(query_url)

        if response.status_code != 200:
            print(f"Erro ao buscar: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        items_html = soup.select("li.ui-search-layout__item")

        results = []
        for item_html in items_html[:limit]:
            # Título e URL
            title_tag = item_html.select_one("a.poly-component__title")
            url_tag = title_tag
            title = title_tag.text.strip() if title_tag else "N/A"
            url = url_tag["href"] if url_tag else None

            if not url:
                continue  # pula anúncios sem link

            # Gerar external_id a partir do link (MLB-xxxx)
            match = re.search(r"MLB-\d+", url)
            external_id = match.group(0) if match else hashlib.md5(url.encode()).hexdigest()

            # Thumbnail
            thumbnail_tag = item_html.select_one("img.poly-component__picture")
            thumbnail_url = thumbnail_tag["src"] if thumbnail_tag else None

            # Preço e moeda
            price_tag = item_html.select_one("span.andes-money-amount__fraction")
            currency_tag = item_html.select_one("span.andes-money-amount__currency-symbol")
            price = float(price_tag.text.replace(".", "")) if price_tag else 0
            currency = currency_tag.text.strip() if currency_tag else "BRL"

            # Ano e km
            attributes = item_html.select("ul.poly-attributes_list li")
            year = int(attributes[0].text.strip()) if len(attributes) > 0 else None
            mileage = int(attributes[1].text.replace(".", "").replace(" Km", "")) if len(attributes) > 1 else None

            # Localização
            location_tag = item_html.select_one("span.poly-component__location")
            location_text = location_tag.text.strip() if location_tag else None
            city, state = (location_text.split(" - ", 1) if location_text and " - " in location_text else (location_text, None))

            # Extrair brand/model/version simples do título
            title_parts = title.split()
            brand = title_parts[0] if len(title_parts) > 0 else None
            model = title_parts[1] if len(title_parts) > 1 else None
            version = " ".join(title_parts[2:5]) if len(title_parts) > 4 else None

            results.append({
                "external_id": external_id,
                "url": url,
                "title": title,
                "description": None,
                "brand": brand,
                "model": model,
                "version": version,
                "year": year,
                "color": None,
                "fuel": None,
                "transmission": None,
                "mileage": mileage,
                "price": price,
                "fipe_price": None,
                "location_state": state,
                "location_city": city,
                "thumbnail_url": thumbnail_url,
                "published_at": datetime.utcnow(),
                "last_seen_at": datetime.utcnow(),
                "is_active": True,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "raw_data": str(item_html)
            })

        return results
