from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_fipe_prices"
down_revision = "0004_car_listings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fipe_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),

        # Identificador "livre" do carro para o MVP (ex.: "Honda Civic 2019 Touring")
        # Depois você pode evoluir para brand/model/year/version codes.
        sa.Column("vehicle_key", sa.Text(), nullable=False),

        sa.Column("fipe_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'BRL'")),

        # Competência (ex.: "2026-01") para saber qual FIPE está valendo
        sa.Column("reference_month", sa.Text(), nullable=False),

        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),

        sa.UniqueConstraint("vehicle_key", "reference_month", name="uq_fipe_vehicle_month"),
    )

    op.create_index("ix_fipe_prices_vehicle_key", "fipe_prices", ["vehicle_key"])

    op.execute("""
    create trigger fipe_prices_updated_at
    before update on fipe_prices
    for each row
    execute function update_updated_at();
    """)


def downgrade():
    op.execute("drop trigger if exists fipe_prices_updated_at on fipe_prices;")
    op.drop_index("ix_fipe_prices_vehicle_key", table_name="fipe_prices")
    op.drop_table("fipe_prices")
