from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session

from app.models.fipe_price import FipePrice


def get_fipe_price(db: Session, vehicle_key: str, reference_month: str) -> Optional[Decimal]:
    row = (
        db.query(FipePrice)
        .filter(FipePrice.vehicle_key == vehicle_key)
        .filter(FipePrice.reference_month == reference_month)
        .first()
    )
    return row.fipe_price if row else None
