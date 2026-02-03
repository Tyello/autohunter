import uuid
from typing import Optional, Any, Dict, List

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY

from app.db.base import Base, TimestampMixin


class SystemLog(TimestampMixin, Base):
    __tablename__ = "system_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # info|warn|error
    level: Mapped[str] = mapped_column(Text, nullable=False, default="info")

    # ex: "scheduler", "scraper_mercadolivre", "scraper_olx", "bot"
    component: Mapped[str] = mapped_column(Text, nullable=False)

    # short label for humans (high-volume)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional structured fields (to power autopilot/agents without parsing JSON)
    # e.g. 'olx', 'webmotors'
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Optional link to a high-level source_runs row
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source_runs.id", ondelete="SET NULL"), nullable=True)

    # machine-readable category, e.g. 'http_blocked', 'parse_failed', 'pipeline_summary'
    event_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # stable dedupe key for the same underlying issue/signal
    fingerprint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)

    # payload livre para debug (jsonb)
    payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
