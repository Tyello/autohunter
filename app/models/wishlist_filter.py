import uuid

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text, ForeignKey, Index, Boolean, true
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class WishlistFilter(TimestampMixin, Base):
    __tablename__ = "wishlist_filters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    wishlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wishlists.id", ondelete="RESTRICT"),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())

    field: Mapped[str] = mapped_column(Text, nullable=False)
    operator: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)

    wishlist = relationship("Wishlist", back_populates="filters")


Index(
    "uq_wishlist_filters_wishlist_field_op_value_active",
    WishlistFilter.wishlist_id,
    WishlistFilter.field,
    WishlistFilter.operator,
    WishlistFilter.value,
    unique=True,
    postgresql_where=WishlistFilter.is_active.is_(True),
    sqlite_where=WishlistFilter.is_active.is_(True),
)
