from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, Any, Dict

from sqlalchemy import BigInteger, DateTime, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminDeployAudit(Base):
    __tablename__ = "admin_deploy_audits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operation_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)

    requested_by_tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    requested_by_username: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    branch: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    before_commit: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    after_commit: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    services_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_tail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
