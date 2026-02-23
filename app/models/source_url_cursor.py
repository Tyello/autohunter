from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class SourceUrlCursor(TimestampMixin, Base):
    """Per-(source,url) cursor for incremental scraping.

    Goal: reduce DB work on 24/7 operation by skipping ingest when the result-set
    hasn't changed (top external_id unchanged), and by ingesting only items that
    appear before the last seen id.
    """

    __tablename__ = "source_url_cursors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    last_external_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
