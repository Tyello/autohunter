import uuid
from typing import Optional, Any, Dict, List

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY

from app.db.base import Base, TimestampMixin


class TelemetryEvent(TimestampMixin, Base):
    """High-signal, structured events for autopilot/agents.

    SystemLog is intentionally generic and high-volume.
    TelemetryEvent is optimized for:
    - dedupe via fingerprint
    - querying by source/event_type
    - attaching minimal evidence (JSONB)
    """

    __tablename__ = "telemetry_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # info|warn|error
    level: Mapped[str] = mapped_column(Text, nullable=False, default="info")

    # e.g. 'olx', 'webmotors'
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # optional link to a high-level source_runs row
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("source_runs.id", ondelete="SET NULL"), nullable=True)

    wishlist_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("wishlists.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    account_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)

    # machine-readable category, e.g. 'http_blocked', 'parse_failed', 'pipeline_summary'
    event_type: Mapped[str] = mapped_column(Text, nullable=False)

    # human-readable short text (optional)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # stable dedupe key for the same underlying issue/signal
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)

    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)

    # minimal evidence for debugging (jsonb)
    evidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
