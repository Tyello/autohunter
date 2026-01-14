# app/services/mercado_livre/ingest.py
from sqlalchemy.orm import Session
from app.models.car_listing import CarListing
from app.services.mercado_livre.scraper import MercadoLivreScraper
from datetime import datetime


class MercadoLivreIngestService:
    def __init__(self, db: Session):
        self.db = db
        self.scraper = MercadoLivreScraper()

    def ingest_search(self, query: str, limit: int = 20) -> int:
        # O scraper agora retorna lista direta
        items = self.scraper.search(query, limit=limit)

        created = 0

        for item in items:
            # evita inserir duplicados (baseado em source + external_id)
            exists = (
                self.db.query(CarListing)
                .filter(CarListing.source == "mercado_livre")
                .filter(CarListing.external_id == item["external_id"])
                .first()
            )
            if exists:
                continue

            listing = CarListing(
                source="mercado_livre",
                external_id=item["external_id"],
                url=item["url"],
                title=item.get("title"),
                description=item.get("description"),
                brand=item.get("brand"),
                model=item.get("model"),
                version=item.get("version"),
                year=item.get("year"),
                color=item.get("color"),
                fuel=item.get("fuel"),
                transmission=item.get("transmission"),
                mileage=item.get("mileage"),
                price=item.get("price", 0),
                fipe_price=item.get("fipe_price"),
                location_state=item.get("location_state"),
                location_city=item.get("location_city"),
                thumbnail_url=item.get("thumbnail_url"),
                published_at=item.get("published_at"),
                last_seen_at=item.get("last_seen_at"),
                is_active=item.get("is_active", True),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

            self.db.add(listing)
            created += 1

        self.db.commit()
        return created
