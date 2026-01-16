import uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text, Boolean
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin

class Account(TimestampMixin, Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False, default="personal")  # personal|team
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    members = relationship("AccountMember", back_populates="account", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="account", cascade="all, delete-orphan")
    users = relationship("User", back_populates="account")
