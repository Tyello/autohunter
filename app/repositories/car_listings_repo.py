from typing import Iterable, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from app.models.car_listing import CarListing


def insert_ignore_duplicates_return_ids(db: Session, rows: Iterable[Dict[str, Any]]) -> List:
    """
    Insere anúncios e ignora duplicados via UNIQUE(source, external_id).
    Retorna lista de IDs que foram realmente inseridos (novos).
    """
    rows_list: List[Dict[str, Any]] = list(rows)
    if not rows_list:
        return []

    stmt = insert(CarListing).values(rows_list)

    # dedupe por UNIQUE (source, external_id)
    stmt = stmt.on_conflict_do_nothing(index_elements=["source", "external_id"])

    # Postgres: retorna IDs só dos inseridos
    stmt = stmt.returning(CarListing.id)

    result = db.execute(stmt)
    inserted_ids = [row[0] for row in result.fetchall()]
    db.commit()
    return inserted_ids
