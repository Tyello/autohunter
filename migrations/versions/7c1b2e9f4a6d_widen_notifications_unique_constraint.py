"""widen notifications unique constraint to include reason and score_v2

Revision ID: 7c1b2e9f4a6d
Revises: d3e5f7a9b1c2
Create Date: 2026-08-31 00:00:00.000000

The old (wishlist_id, car_listing_id) constraint blocks
queue_tracked_price_drop_alert from ever inserting a second notification
for a wishlist+listing pair that already has a "match" notification,
raising an unhandled IntegrityError. Widen it to (wishlist_id,
car_listing_id, reason, score_v2) to match the de-dup key the
application already checks in code, and give "match" notifications an
explicit reason="match" (was NULL) so they keep being deduped correctly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c1b2e9f4a6d'
down_revision: Union[str, Sequence[str], None] = 'd3e5f7a9b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute(
        sa.text("UPDATE notifications SET reason = 'match' WHERE reason IS NULL")
    )
    op.drop_constraint(
        "uq_notifications_wishlist_listing",
        "notifications",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_notifications_wishlist_listing_reason_score",
        "notifications",
        ["wishlist_id", "car_listing_id", "reason", "score_v2"],
    )


def downgrade():
    op.drop_constraint(
        "uq_notifications_wishlist_listing_reason_score",
        "notifications",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_notifications_wishlist_listing",
        "notifications",
        ["wishlist_id", "car_listing_id"],
    )
