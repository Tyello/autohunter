from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class UserDigestPreference(TimestampMixin, Base):
    __tablename__ = "user_digest_preferences"
    __table_args__ = (
        CheckConstraint("digest_days >= 1 AND digest_days <= 30", name="ck_user_digest_preferences_days_range"),
        CheckConstraint("digest_limit >= 1 AND digest_limit <= 20", name="ck_user_digest_preferences_limit_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        unique=True,
        nullable=False,
    )
    weekly_digest_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    digest_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    digest_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    last_digest_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_digest_previewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
