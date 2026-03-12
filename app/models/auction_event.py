"""
Modelo: AuctionEvent

Representa um evento/sessão de leilão.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ARRAY, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime

from app.db.base_class import Base


class AuctionEvent(Base):
    """Evento/Sessão de Leilão."""
    
    __tablename__ = "auction_events"
    
    # Primary Key
    id = Column(Integer, primary_key=True, index=True)
    
    # Identificação
    external_id = Column(String(255), nullable=False, index=True)
    source = Column(String(100), nullable=False, index=True)
    
    # Informações básicas
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    url = Column(Text, nullable=False)
    
    # Datas e horários
    event_date = Column(DateTime(timezone=True), nullable=True, index=True)
    registration_deadline = Column(DateTime(timezone=True), nullable=True)
    viewing_start = Column(DateTime(timezone=True), nullable=True)
    viewing_end = Column(DateTime(timezone=True), nullable=True)
    
    # Status
    status = Column(String(50), nullable=False, index=True, default="scheduled")
    # Valores: scheduled, live, ended, cancelled
    
    # Localização
    location = Column(Text, nullable=True)
    city = Column(String(255), nullable=True, index=True)
    state = Column(String(2), nullable=True, index=True)
    
    # Estatísticas
    total_lots = Column(Integer, nullable=True)
    vehicle_lots = Column(Integer, nullable=True)
    
    # Tipo
    auction_type = Column(String(50), nullable=True)
    # Valores: judicial, extrajudicial, government, private
    modality = Column(String(50), nullable=True)
    # Valores: online, presencial, hibrido
    
    # Organização
    auctioneer = Column(String(255), nullable=True)
    organizer = Column(String(255), nullable=True)
    
    # Extras
    extras = Column(JSONB, nullable=True)
    raw_payload = Column(JSONB, nullable=True)
    
    # Metadados
    extractor_version = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, 
                       onupdate=datetime.utcnow, nullable=False)
    
    # Relacionamentos
    lots = relationship("AuctionLot", back_populates="event")
    
    # Índices compostos
    __table_args__ = (
        Index('ix_auction_events_status_event_date', 'status', 'event_date'),
        Index('uq_auction_events_source_external_id', 'source', 'external_id', unique=True),
    )
    
    def __repr__(self):
        return f"<AuctionEvent(id={self.id}, source={self.source}, title={self.title[:30]})>"
    
    @property
    def is_upcoming(self) -> bool:
        """Verifica se evento está programado para o futuro."""
        if not self.event_date:
            return False
        return self.event_date > datetime.utcnow()
    
    @property
    def is_live(self) -> bool:
        """Verifica se evento está ao vivo."""
        return self.status == "live"
    
    @property
    def is_ended(self) -> bool:
        """Verifica se evento já terminou."""
        return self.status == "ended"
    
    def to_dict(self):
        """Converte para dicionário."""
        return {
            "id": self.id,
            "external_id": self.external_id,
            "source": self.source,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "status": self.status,
            "location": self.location,
            "city": self.city,
            "state": self.state,
            "total_lots": self.total_lots,
            "vehicle_lots": self.vehicle_lots,
            "auction_type": self.auction_type,
            "modality": self.modality,
            "auctioneer": self.auctioneer,
            "organizer": self.organizer,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
