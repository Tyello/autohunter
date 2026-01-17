from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_source_metrics"
down_revision = "ec4a5f769526"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False, unique=True),
        sa.Column("next_allowed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_blocks", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_status", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_source_states_source", "source_states", ["source"], unique=True)
    op.create_index("ix_source_states_next_allowed_at", "source_states", ["next_allowed_at"])

    op.execute("""
    create trigger source_states_updated_at
    before update on source_states
    for each row
    execute function update_updated_at();
    """)

    op.create_table(
        "source_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("items_found", sa.Integer(), nullable=True),
        sa.Column("items_ingested", sa.Integer(), nullable=True),
        sa.Column("items_matched", sa.Integer(), nullable=True),
        sa.Column("notifications_queued", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_source_runs_source_created_at", "source_runs", ["source", "created_at"])
    op.create_index("ix_source_runs_status_created_at", "source_runs", ["status", "created_at"])

    op.execute("""
    create trigger source_runs_updated_at
    before update on source_runs
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.execute("drop trigger if exists source_runs_updated_at on source_runs;")
    op.drop_index("ix_source_runs_status_created_at", table_name="source_runs")
    op.drop_index("ix_source_runs_source_created_at", table_name="source_runs")
    op.drop_table("source_runs")

    op.execute("drop trigger if exists source_states_updated_at on source_states;")
    op.drop_index("ix_source_states_next_allowed_at", table_name="source_states")
    op.drop_index("ix_source_states_source", table_name="source_states")
    op.drop_table("source_states")
