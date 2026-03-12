from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_wishlist_filters"
down_revision = "0003_wishlists"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wishlist_filters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),

        sa.Column("wishlist_id", postgresql.UUID(as_uuid=True), nullable=False),

        # filtro simples e extensível (sem inventar “engine” complexa)
        # exemplos:
        # field="price", operator="lte", value="80000"
        # field="year", operator="gte", value="2018"
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("operator", sa.Text(), nullable=False),  # eq|neq|lt|lte|gt|gte|contains
        sa.Column("value", sa.Text(), nullable=False),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        sa.ForeignKeyConstraint(["wishlist_id"], ["wishlists.id"], ondelete="RESTRICT"),
    )

    op.create_index("ix_wishlist_filters_wishlist_id", "wishlist_filters", ["wishlist_id"])
    op.create_index("ix_wishlist_filters_field", "wishlist_filters", ["field"])

    # opcional, mas recomendável para evitar filtros duplicados idênticos na mesma wishlist
    op.create_unique_constraint(
        "uq_wishlist_filters_wishlist_field_op_value",
        "wishlist_filters",
        ["wishlist_id", "field", "operator", "value"],
    )

    op.execute("""
    create trigger wishlist_filters_updated_at
    before update on wishlist_filters
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.execute("drop trigger if exists wishlist_filters_updated_at on wishlist_filters;")
    op.drop_constraint("uq_wishlist_filters_wishlist_field_op_value", "wishlist_filters", type_="unique")
    op.drop_index("ix_wishlist_filters_field", table_name="wishlist_filters")
    op.drop_index("ix_wishlist_filters_wishlist_id", table_name="wishlist_filters")
    op.drop_table("wishlist_filters")
