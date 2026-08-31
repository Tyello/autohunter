"""fix fipe_lookup_requests.wishlist_id ondelete to RESTRICT

Revision ID: 9b2d4f6a8c1e
Revises: 7c1b2e9f4a6d
Create Date: 2026-08-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '9b2d4f6a8c1e'
down_revision: Union[str, Sequence[str], None] = '7c1b2e9f4a6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "fipe_lookup_requests_wishlist_id_fkey",
        "fipe_lookup_requests",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fipe_lookup_requests_wishlist_id_fkey",
        "fipe_lookup_requests",
        "wishlists",
        ["wishlist_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # Intentional no-op: this repo's delete-safety policy forbids ON DELETE
    # CASCADE on any FK, so downgrade does not restore the old behavior.
    pass
