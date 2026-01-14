from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_car_listings"
down_revision = "0003_wishlists"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "car_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),

        # Deduplicação por fonte + id externo
        sa.Column("source", sa.Text(), nullable=False),        # "mercadolivre" | "olx"
        sa.Column("external_id", sa.Text(), nullable=False),

        # Dados do anúncio (mínimo p/ MVP)
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),

        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'BRL'")),

        # Opcional, mas útil p/ matching depois
        sa.Column("location", sa.Text(), nullable=True),

        # timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        sa.UniqueConstraint("source", "external_id", name="uq_car_listings_source_external_id"),
    )

    op.create_index("ix_car_listings_source", "car_listings", ["source"])
    op.create_index("ix_car_listings_created_at", "car_listings", ["created_at"])

    op.execute("""
    create trigger car_listings_updated_at
    before update on car_listings
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.execute("drop trigger if exists car_listings_updated_at on car_listings;")
    op.drop_index("ix_car_listings_created_at", table_name="car_listings")
    op.drop_index("ix_car_listings_source", table_name="car_listings")
    op.drop_table("car_listings")
