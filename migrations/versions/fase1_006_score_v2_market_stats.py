"""Score v2 breakdown + market stats table

Revision ID: fase1_006_score_v2
Revises: fase1_005_cursors_sold
Create Date: 2026-02-22

- Adds `score_v2` and `score_breakdown` (JSONB) to notifications.
- Creates `market_stats_cohorts` table (daily cohort stats: make+model+year).

Rationale:
Score v2 is wishlist-specific, so we persist the breakdown at Notification level.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "fase1_006_score_v2"
down_revision = "fase1_005_cursors_sold"
branch_labels = None
depends_on = None


def upgrade():
    # --- notifications: score breakdown persisted per (wishlist_id, car_listing_id)
    op.add_column("notifications", sa.Column("score_v2", sa.Integer(), nullable=True))
    op.add_column(
        "notifications",
        sa.Column("score_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_index(
        "ix_notifications_score_v2",
        "notifications",
        ["score_v2"],
        postgresql_where=sa.text("score_v2 IS NOT NULL"),
    )

    # --- market_stats_cohorts
    op.create_table(
        "market_stats_cohorts",
        sa.Column("make", sa.Text(), primary_key=True),
        sa.Column("model", sa.Text(), primary_key=True),
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("median_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("p25_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("p75_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_market_stats_cohorts_year", "market_stats_cohorts", ["year"])
    op.create_index("ix_market_stats_cohorts_make_model", "market_stats_cohorts", ["make", "model"])

    # updated_at trigger
    op.execute(
        """
        create trigger market_stats_cohorts_updated_at
        before update on market_stats_cohorts
        for each row
        execute function update_updated_at();
        """
    )


def downgrade():
    op.execute("drop trigger if exists market_stats_cohorts_updated_at on market_stats_cohorts;")
    op.drop_index("ix_market_stats_cohorts_make_model", table_name="market_stats_cohorts")
    op.drop_index("ix_market_stats_cohorts_year", table_name="market_stats_cohorts")
    op.drop_table("market_stats_cohorts")

    op.drop_index("ix_notifications_score_v2", table_name="notifications")
    op.drop_column("notifications", "score_breakdown")
    op.drop_column("notifications", "score_v2")
