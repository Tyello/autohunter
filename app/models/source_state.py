import uuid
from datetime import datetime
from typing import Optional, Any, Dict

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base, TimestampMixin


class SourceState(TimestampMixin, Base):
    """Estado operacional de uma fonte (backoff / saúde).

    - next_allowed_at: quando a fonte pode voltar a rodar
    - consecutive_blocks: quantas execuções seguidas terminaram em bloqueio (403/429)
    - consecutive_failures: quantas execuções seguidas terminaram em erro (exceção)
    """

    __tablename__ = "source_states"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    next_allowed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    consecutive_blocks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # success|blocked|error|skipped
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
