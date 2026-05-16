import uuid
from typing import Optional, Any, Dict

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base, TimestampMixin


class SourceConfig(TimestampMixin, Base):
    """Configuração operacional por fonte.

    A ideia é que *todas* as sources tenham os mesmos knobs controláveis
    (enable/schedule/cooldown/rate-limit/proxy/flags de browser), evitando
    espalhar controle em env/settings.
    """

    __tablename__ = "source_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, default="classified")
    user_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    admin_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sched_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rate_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    proxy_server: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Browser/híbrido
    browser_fallback_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    force_browser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    extra: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
