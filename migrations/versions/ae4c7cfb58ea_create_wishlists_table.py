from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_wishlists"
down_revision = "0002_users"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wishlists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Mantém simples: um "query" que representa a busca do usuário (texto)
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_wishlists_user_id", "wishlists", ["user_id"])

    op.execute("""
    create trigger wishlists_updated_at
    before update on wishlists
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.execute("drop trigger if exists wishlists_updated_at on wishlists;")
    op.drop_index("ix_wishlists_user_id", table_name="wishlists")
    op.drop_table("wishlists")
