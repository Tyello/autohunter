"""
Auction Lot Service

Serviço para gerenciar lotes de leilão.
"""

from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from datetime import datetime

from app.models.auction_lot import AuctionLot


def get_lot_by_id(db: Session, lot_id: int) -> Optional[AuctionLot]:
    """Busca lote por ID."""
    return db.query(AuctionLot).filter(AuctionLot.id == lot_id).first()


def get_lot_by_external_id(db: Session, source: str, external_id: str) -> Optional[AuctionLot]:
    """Busca lote por fonte e ID externo."""
    return db.query(AuctionLot).filter(
        and_(
            AuctionLot.source == source,
            AuctionLot.external_id == external_id
        )
    ).first()


def create_lot(db: Session, lot_data: dict) -> AuctionLot:
    """Cria novo lote."""
    lot = AuctionLot(**lot_data)
    db.add(lot)
    db.commit()
    db.refresh(lot)
    return lot


def update_lot(db: Session, lot: AuctionLot, update_data: dict) -> AuctionLot:
    """Atualiza lote existente."""
    for key, value in update_data.items():
        if hasattr(lot, key):
            setattr(lot, key, value)
    
    lot.last_seen_at = datetime.utcnow()
    lot.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(lot)
    return lot


def upsert_lot(db: Session, lot_data: dict) -> tuple[AuctionLot, bool]:
    """Cria ou atualiza lote.
    
    Returns:
        (lot, created) onde created=True se foi criado novo
    """
    source = lot_data.get("source")
    external_id = lot_data.get("external_id")
    
    if not source or not external_id:
        raise ValueError("source and external_id are required")
    
    existing = get_lot_by_external_id(db, source, external_id)
    
    if existing:
        lot = update_lot(db, existing, lot_data)
        return lot, False
    else:
        lot = create_lot(db, lot_data)
        return lot, True


def search_lots(
    db: Session,
    source: Optional[str] = None,
    status: Optional[str] = None,
    item_type: Optional[str] = None,
    make: Optional[str] = None,
    model: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    min_bid: Optional[float] = None,
    max_bid: Optional[float] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[AuctionLot]:
    """Busca lotes com filtros."""
    
    query = db.query(AuctionLot)
    
    if source:
        query = query.filter(AuctionLot.source == source)
    
    if status:
        query = query.filter(AuctionLot.status == status)
    
    if item_type:
        query = query.filter(AuctionLot.item_type == item_type)
    
    if make:
        query = query.filter(AuctionLot.make.ilike(f"%{make}%"))
    
    if model:
        query = query.filter(AuctionLot.model.ilike(f"%{model}%"))
    
    if city:
        query = query.filter(AuctionLot.city.ilike(f"%{city}%"))
    
    if state:
        query = query.filter(AuctionLot.state == state)
    
    if min_bid is not None:
        query = query.filter(AuctionLot.initial_bid >= min_bid)
    
    if max_bid is not None:
        query = query.filter(AuctionLot.initial_bid <= max_bid)
    
    # Ordenação: próximos primeiro, depois por lance
    query = query.order_by(
        AuctionLot.status.asc(),
        AuctionLot.initial_bid.asc(),
        AuctionLot.created_at.desc()
    )
    
    return query.offset(offset).limit(limit).all()


def get_lots_by_event(db: Session, event_id: int, limit: int = 100) -> List[AuctionLot]:
    """Busca lotes de um evento."""
    return db.query(AuctionLot).filter(
        AuctionLot.event_id == event_id
    ).order_by(
        AuctionLot.lot_number.asc()
    ).limit(limit).all()


def get_active_lots(db: Session, limit: int = 100) -> List[AuctionLot]:
    """Busca lotes ativos (scheduled ou live)."""
    return db.query(AuctionLot).filter(
        or_(
            AuctionLot.status == "scheduled",
            AuctionLot.status == "live"
        )
    ).order_by(
        AuctionLot.created_at.desc()
    ).limit(limit).all()


def count_lots_by_source(db: Session) -> dict:
    """Conta lotes por fonte."""
    from sqlalchemy import func
    
    results = db.query(
        AuctionLot.source,
        func.count(AuctionLot.id).label("count")
    ).group_by(
        AuctionLot.source
    ).all()
    
    return {source: count for source, count in results}


def delete_old_lots(db: Session, days: int = 90) -> int:
    """Deleta lotes antigos (ended/sold/unsold)."""
    from datetime import timedelta
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    deleted = db.query(AuctionLot).filter(
        and_(
            or_(
                AuctionLot.status == "ended",
                AuctionLot.status == "sold",
                AuctionLot.status == "unsold"
            ),
            AuctionLot.last_seen_at < cutoff
        )
    ).delete()
    
    db.commit()
    
    return deleted
