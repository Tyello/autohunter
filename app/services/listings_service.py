from sqlalchemy.orm import Session
from app.repositories.car_listings_repo import insert_ignore_duplicates_return_ids

def ingest_listings(db: Session, listings: list[dict]):
    if not listings:
        return []
    inserted_ids = insert_ignore_duplicates_return_ids(db, listings)
    return list(inserted_ids or [])
