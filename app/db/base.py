"""SQLAlchemy Base + common mixins.

Why this file exists:
- Centralize the Declarative Base.
- Provide common timestamp columns.

⚠️  Important:
This module intentionally imports `app.models` **only at the end**.
Importing models before `Base` exists causes circular imports (models import
Base from here, while this file tries to import models).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# Import models for Alembic autogenerate / metadata registration.
# noqa: F401,E402
import app.models  # isort: skip
