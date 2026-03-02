from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class FBAgentSession(TimestampMixin, Base):
    __tablename__ = "fb_agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)

    pairing_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    pairing_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    pairing_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING_AGENT", index=True)

    agent_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    agent_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    last_error_kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    action_hint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    bootstrap_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    bootstrap_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    bootstrap_token_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
