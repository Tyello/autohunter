from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid

from app.db.base import Base, TimestampMixin


class Wishlist(TimestampMixin, Base):
    __tablename__ = "wishlists"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user = relationship("User", back_populates="wishlists")

    filters = relationship(
        "WishlistFilter",
        back_populates="wishlist",
        cascade="all, delete-orphan",
    )

    # Scalable matching: inverted index tokens (token -> wishlist)
    # PK is (wishlist_id, token) in wishlist_tokens table.
    tokens = relationship(
        "WishlistToken",
        back_populates="wishlist",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
