import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

class Subscription(TimestampMixin, Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False)

    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    daily_alert_limit_override: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # starts_at é NOT NULL no banco. Sem default aqui, o SQLAlchemy pode enviar NULL
    # mesmo existindo server_default no Postgres (dependendo de como o objeto foi instanciado).
    # Então colocamos:
    # - default (client-side) para nunca gerar None
    # - server_default (db-side) para blindar regressões
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")

    account = relationship("Account", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")
