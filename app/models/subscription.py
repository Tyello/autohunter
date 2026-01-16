import uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import ForeignKey

from app.db.base import Base, TimestampMixin

class Subscription(TimestampMixin, Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False)

    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    daily_alert_limit_override: Mapped[int | None] = mapped_column(Integer, nullable=True)

    starts_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")

    account = relationship("Account", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")
