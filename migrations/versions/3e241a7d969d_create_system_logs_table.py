from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_system_logs"
down_revision = "0006_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "system_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),

        sa.Column("level", sa.Text(), nullable=False, server_default=sa.text("'info'")),  # info|warn|error
        sa.Column("component", sa.Text(), nullable=False),  # ex: "scheduler", "scraper_olx", "bot"
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_system_logs_level", "system_logs", ["level"])
    op.create_index("ix_system_logs_created_at", "system_logs", ["created_at"])

    op.execute("""
    create trigger system_logs_updated_at
    before update on system_logs
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.execute("drop trigger if exists system_logs_updated_at on system_logs;")
    op.drop_index("ix_system_logs_created_at", table_name="system_logs")
    op.drop_index("ix_system_logs_level", table_name="system_logs")
    op.drop_table("system_logs")
