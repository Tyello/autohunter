import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FipeUpdateRun(Base):
    __tablename__ = "fipe_update_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    updated_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_month: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    lock_key: Mapped[str] = mapped_column(Text, nullable=False, default="monthly_fipe_update")
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('running','completed','failed','skipped')", name="ck_fipe_update_runs_status"),
        Index("ix_fipe_update_runs_started_at", "started_at"),
        Index("ix_fipe_update_runs_status_started", "status", "started_at"),
        Index("ix_fipe_update_runs_lock_status", "lock_key", "status"),
    )
