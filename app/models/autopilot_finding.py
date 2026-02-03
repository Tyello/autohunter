import uuid
from datetime import datetime
from typing import Optional, Any, Dict

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base, TimestampMixin


class AutopilotFinding(TimestampMixin, Base):
    """Sinais detectados automaticamente a partir de SourceRuns/SystemLogs.

    Objetivo: manter histórico de regressões/bloqueios/quebras, com dedupe por fingerprint,
    e alertar admins sem spam.
    """

    __tablename__ = "autopilot_findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # open|closed
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open")

    # blocked_spike|error_spike|found_drop|log_error_burst|...
    kind: Mapped[str] = mapped_column(Text, nullable=False)

    # fonte relacionada (quando aplicável)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # dedupe key (sha1 etc)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)

    severity: Mapped[str] = mapped_column(Text, nullable=False, default="warn")  # info|warn|error

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    last_alert_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    evidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    suggested_actions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
