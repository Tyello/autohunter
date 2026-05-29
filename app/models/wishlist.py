from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text, Boolean, ForeignKey, false, DateTime
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

from app.db.base import Base, TimestampMixin


class Wishlist(TimestampMixin, Base):
    __tablename__ = "wishlists"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_auctions: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="wishlists")

    filters = relationship(
        "WishlistFilter",
        back_populates="wishlist",
    )

    # Scalable matching: inverted index tokens (token -> wishlist)
    tokens = relationship(
        "WishlistToken",
        back_populates="wishlist",
    )

    tracked_listings = relationship(
        "WishlistTrackedListing",
    )
