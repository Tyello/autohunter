from typing import Iterable, Dict, Any, List
from sqlalchemy.orm import Session

from app.repositories.car_listings_repo import insert_ignore_duplicates_return_ids


def ingest_listings(db: Session, listings: Iterable[Dict[str, Any]]) -> List:
    """
    Persiste anúncios e retorna IDs dos anúncios novos inseridos.
    """
    return insert_ignore_duplicates_return_ids(db, listings)
