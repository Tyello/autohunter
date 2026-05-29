"""protect core user/wishlist tables from accidental destructive deletes

Revision ID: 5c8f1a2b3d4e
Revises: e7a1c9f2b4d3
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "5c8f1a2b3d4e"
down_revision = "e7a1c9f2b4d3"
branch_labels = None
depends_on = None


PROTECTED_CORE_TABLES = (
    "users",
    "wishlists",
    "wishlist_filters",
    "wishlist_tokens",
    "wishlist_tracked_listings",
    "wishlist_listing_activity",
    "notifications",
    "account_members",
    "user_digest_preferences",
)

_FUNCTION_NAME = "prevent_core_data_delete_without_guard"
_DELETE_TRIGGER_PREFIX = "trg_prevent_core_data_delete_without_guard"
_TRUNCATE_TRIGGER_PREFIX = "trg_prevent_core_data_truncate_without_guard"


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.add_column("wishlists", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wishlist_filters", sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("wishlist_tracked_listings", sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False))

    op.drop_constraint("uq_wishlist_filters_wishlist_field_op_value", "wishlist_filters", type_="unique")
    op.create_index(
        "uq_wishlist_filters_wishlist_field_op_value_active",
        "wishlist_filters",
        ["wishlist_id", "field", "operator", "value"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.drop_constraint("uq_wishlist_tracked_listing_pair", "wishlist_tracked_listings", type_="unique")
    op.drop_constraint("uq_wishlist_tracked_listing_slot", "wishlist_tracked_listings", type_="unique")
    op.create_index(
        "uq_wishlist_tracked_listing_pair_active",
        "wishlist_tracked_listings",
        ["wishlist_id", "car_listing_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.create_index(
        "uq_wishlist_tracked_listing_slot_active",
        "wishlist_tracked_listings",
        ["wishlist_id", "slot"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )

    op.execute(
        text(
            f"""
            CREATE OR REPLACE FUNCTION public.{_FUNCTION_NAME}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF COALESCE(current_setting('app.allow_core_data_delete', true), '') <> 'on' THEN
                    RAISE EXCEPTION
                        'Blocked % on protected core table %.%. Set app.allow_core_data_delete=on inside an explicit break-glass transaction to proceed.',
                        TG_OP,
                        TG_TABLE_SCHEMA,
                        TG_TABLE_NAME
                        USING ERRCODE = '42501';
                END IF;

                RETURN NULL;
            END;
            $$;
            """
        )
    )

    for table in PROTECTED_CORE_TABLES:
        op.execute(text(f"DROP TRIGGER IF EXISTS {_q(_DELETE_TRIGGER_PREFIX)} ON public.{_q(table)};"))
        op.execute(text(f"DROP TRIGGER IF EXISTS {_q(_TRUNCATE_TRIGGER_PREFIX)} ON public.{_q(table)};"))
        op.execute(
            text(
                f"""
                CREATE TRIGGER {_q(_DELETE_TRIGGER_PREFIX)}
                BEFORE DELETE ON public.{_q(table)}
                FOR EACH STATEMENT
                EXECUTE FUNCTION public.{_FUNCTION_NAME}();
                """
            )
        )
        op.execute(
            text(
                f"""
                CREATE TRIGGER {_q(_TRUNCATE_TRIGGER_PREFIX)}
                BEFORE TRUNCATE ON public.{_q(table)}
                FOR EACH STATEMENT
                EXECUTE FUNCTION public.{_FUNCTION_NAME}();
                """
            )
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in PROTECTED_CORE_TABLES:
        op.execute(text(f"DROP TRIGGER IF EXISTS {_q(_DELETE_TRIGGER_PREFIX)} ON public.{_q(table)};"))
        op.execute(text(f"DROP TRIGGER IF EXISTS {_q(_TRUNCATE_TRIGGER_PREFIX)} ON public.{_q(table)};"))
    op.execute(text(f"DROP FUNCTION IF EXISTS public.{_FUNCTION_NAME}();"))

    op.drop_index("uq_wishlist_tracked_listing_slot_active", table_name="wishlist_tracked_listings")
    op.drop_index("uq_wishlist_tracked_listing_pair_active", table_name="wishlist_tracked_listings")
    op.create_unique_constraint(
        "uq_wishlist_tracked_listing_slot",
        "wishlist_tracked_listings",
        ["wishlist_id", "slot"],
    )
    op.create_unique_constraint(
        "uq_wishlist_tracked_listing_pair",
        "wishlist_tracked_listings",
        ["wishlist_id", "car_listing_id"],
    )
    op.drop_index("uq_wishlist_filters_wishlist_field_op_value_active", table_name="wishlist_filters")
    op.create_unique_constraint(
        "uq_wishlist_filters_wishlist_field_op_value",
        "wishlist_filters",
        ["wishlist_id", "field", "operator", "value"],
    )
    op.drop_column("wishlist_tracked_listings", "is_active")
    op.drop_column("wishlist_filters", "is_active")
    op.drop_column("wishlists", "deleted_at")
