import uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text, Integer, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


PLAN_CODE_FREE = "free"
PLAN_CODE_PRO = "pro"
PLAN_CODE_ULTRA = "ultra"

class Plan(TimestampMixin, Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # free|pro|ultra
    name: Mapped[str] = mapped_column(Text, nullable=False)
    daily_alert_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    max_wishlists: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    subscriptions = relationship("Subscription", back_populates="plan")
