from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_notifications"
down_revision = "0005_fipe_prices"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),

        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wishlist_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("car_listing_id", postgresql.UUID(as_uuid=True), nullable=False),

        # Controle básico
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),  # queued|sent|failed
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wishlist_id"], ["wishlists.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["car_listing_id"], ["car_listings.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    op.create_index("ix_notifications_status", "notifications", ["status"])

    op.execute("""
    create trigger notifications_updated_at
    before update on notifications
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.execute("drop trigger if exists notifications_updated_at on notifications;")
    op.drop_index("ix_notifications_status", table_name="notifications")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
