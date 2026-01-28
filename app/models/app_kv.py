from __future__ import annotations

from typing import Optional, Any, Dict

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base, TimestampMixin


class AppKV(TimestampMixin, Base):
    """Key/Value simples (JSONB) para ponteiros e configs operacionais.

    Uso:
    - cursor do monitor admin
    - throttle/dedupe simples
    """

    __tablename__ = "app_kv"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
