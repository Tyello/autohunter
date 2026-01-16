import uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import ForeignKey

from app.db.base import Base

class AccountMember(Base):
    __tablename__ = "account_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="owner")

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)

    account = relationship("Account", back_populates="members")
    user = relationship("User")
