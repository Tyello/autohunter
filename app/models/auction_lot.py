"""
Modelo: AuctionLot

Representa um lote de leilão (veículo ou outro bem).
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Numeric, ARRAY, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime
from decimal import Decimal

from app.db.base_class import Base


class AuctionLot(Base):
    """Lote de Leilão."""
    
    __tablename__ = "auction_lots"
    
    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # Relação com evento
    event_id = Column(Integer, ForeignKey("auction_events.id", ondelete="SET NULL"), nullable=True)
    
    # Identificação
    external_id = Column(String(255), nullable=False, index=True)
    source = Column(String(100), nullable=False, index=True)
    lot_number = Column(String(50), nullable=True)
    
    # Informações básicas
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    url = Column(Text, nullable=False)
    thumbnail_url = Column(Text, nullable=True)
    
    # Tipo de bem
    item_type = Column(String(50), nullable=False, index=True, default="vehicle")
    # Valores: vehicle, motorcycle, boat, other
    
    # Informações de veículo
    make = Column(String(100), nullable=True, index=True)
    model = Column(String(100), nullable=True, index=True)
    year = Column(Integer, nullable=True, index=True)
    mileage_km = Column(Integer, nullable=True)
    fuel_type = Column(String(50), nullable=True)
    transmission = Column(String(50), nullable=True)
    color = Column(String(50), nullable=True)
    plate = Column(String(20), nullable=True)
    chassis = Column(String(50), nullable=True)
    
    # Valores e lances
    initial_bid = Column(Numeric(12, 2), nullable=True, index=True)
    current_bid = Column(Numeric(12, 2), nullable=True)
    minimum_bid = Column(Numeric(12, 2), nullable=True)
    estimated_value = Column(Numeric(12, 2), nullable=True)
    reserve_price = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="BRL")
    
    # Incremento
    bid_increment = Column(Numeric(12, 2), nullable=True)
    
    # Número de lances
    total_bids = Column(Integer, nullable=True)
    
    # Status
    status = Column(String(50), nullable=False, index=True, default="scheduled")
    # Valores: scheduled, live, sold, unsold, cancelled
    
    # Localização do bem
    location = Column(Text, nullable=True)
    city = Column(String(255), nullable=True, index=True)
    state = Column(String(2), nullable=True, index=True)
    
    # Condição
    condition = Column(String(50), nullable=True)
    # Valores: new, used, damaged, salvage
    condition_notes = Column(Text, nullable=True)
    
    # Documentação
    has_documentation = Column(Boolean, nullable=True)
    documentation_notes = Column(Text, nullable=True)
    
    # Débitos
    has_debts = Column(Boolean, nullable=True)
    debt_amount = Column(Numeric(12, 2), nullable=True)
    debt_notes = Column(Text, nullable=True)
    
    # Visitação
    viewing_available = Column(Boolean, nullable=True)
    viewing_location = Column(Text, nullable=True)
    viewing_notes = Column(Text, nullable=True)
    
    # Imagens
    image_count = Column(Integer, nullable=True)
    images = Column(ARRAY(Text), nullable=True)
    
    # Extras
    extras = Column(JSONB, nullable=True)
    raw_payload = Column(JSONB, nullable=True)
    
    # Metadados
    extractor_version = Column(String(50), nullable=True)
    first_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=datetime.utcnow, 
                         onupdate=datetime.utcnow, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, 
                       onupdate=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    event = relationship("AuctionEvent", back_populates="lots")
    
    # Índices compostos
    __table_args__ = (
        Index('ix_auction_lots_make_model', 'make', 'model'),
        Index('ix_auction_lots_type_status_city', 'item_type', 'status', 'city'),
        Index('uq_auction_lots_source_external_id', 'source', 'external_id', unique=True),
    )
    
    def __repr__(self):
        return f"<AuctionLot(id={self.id}, source={self.source}, lot={self.lot_number}, title={self.title[:30]})>"
    
    @property
    def is_vehicle(self) -> bool:
        """Verifica se é veículo."""
        return self.item_type == "vehicle"
    
    @property
    def is_sold(self) -> bool:
        """Verifica se foi vendido."""
        return self.status == "sold"
    
    @property
    def has_minimum_bid(self) -> bool:
        """Verifica se tem lance inicial."""
        return self.initial_bid is not None and self.initial_bid > 0
    
    @property
    def price_per_description(self) -> str:
        """Retorna descrição do preço."""
        if self.current_bid:
            return f"Lance atual: R$ {self.current_bid:,.2f}"
        elif self.initial_bid:
            return f"Lance inicial: R$ {self.initial_bid:,.2f}"
        elif self.estimated_value:
            return f"Avaliação: R$ {self.estimated_value:,.2f}"
        return "Preço não informado"
    
    def to_dict(self):
        """Converte para dicionário."""
        return {
            "id": self.id,
            "event_id": self.event_id,
            "external_id": self.external_id,
            "source": self.source,
            "lot_number": self.lot_number,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "thumbnail_url": self.thumbnail_url,
            "item_type": self.item_type,
            "make": self.make,
            "model": self.model,
            "year": self.year,
            "mileage_km": self.mileage_km,
            "fuel_type": self.fuel_type,
            "transmission": self.transmission,
            "color": self.color,
            "initial_bid": float(self.initial_bid) if self.initial_bid else None,
            "current_bid": float(self.current_bid) if self.current_bid else None,
            "estimated_value": float(self.estimated_value) if self.estimated_value else None,
            "status": self.status,
            "location": self.location,
            "city": self.city,
            "state": self.state,
            "condition": self.condition,
            "has_documentation": self.has_documentation,
            "has_debts": self.has_debts,
            "viewing_available": self.viewing_available,
            "image_count": self.image_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
