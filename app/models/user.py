from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text, BigInteger, Boolean, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from app.db.base import Base, TimestampMixin

class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_daily_limit_notice_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="free")
    daily_limit_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    account = relationship("Account", back_populates="users")

    wishlists = relationship("Wishlist", back_populates="user", cascade="all, delete-orphan")
