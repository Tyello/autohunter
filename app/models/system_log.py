import uuid
from typing import Optional, Any, Dict

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import UUID, JSONB

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

    message: Mapped[str] = mapped_column(Text, nullable=False)

    # payload livre para debug (jsonb)
    payload: Mapped[Optional[Dict[str, Any]]] = Mapped
