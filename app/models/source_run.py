import uuid
from typing import Optional, Any, Dict

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base, TimestampMixin


class SourceRun(TimestampMixin, Base):
    """Métricas por execução (uma linha por run)."""

    __tablename__ = "source_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source: Mapped[str] = mapped_column(Text, nullable=False)

    # scheduler|manual
    kind: Mapped[str] = mapped_column(Text, nullable=False)

    query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # success|blocked|error|skipped
    status: Mapped[str] = mapped_column(Text, nullable=False)

    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    items_found: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    items_ingested: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    items_matched: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notifications_queued: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
