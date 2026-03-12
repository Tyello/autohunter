"""remove fk cascades and enforce explicit deletes

Revision ID: 9a6f3e2d1c4b
Revises: e8d0d6f4a21b
Create Date: 2026-03-12 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9a6f3e2d1c4b"
down_revision: Union[str, Sequence[str], None] = "e8d0d6f4a21b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_fk(
    table: str,
    local_cols: list[str],
    referred_table: str,
    referred_cols: list[str],
    new_name: str,
    ondelete: str,
) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for fk in insp.get_foreign_keys(table):
        if fk.get("referred_table") != referred_table:
            continue
        if list(fk.get("constrained_columns") or []) != list(local_cols):
            continue
        name = fk.get("name")
        if name:
            op.drop_constraint(name, table_name=table, type_="foreignkey")

    op.create_foreign_key(
        new_name,
        source_table=table,
        referent_table=referred_table,
        local_cols=local_cols,
        remote_cols=referred_cols,
        ondelete=ondelete,
    )


def upgrade() -> None:
    # Domain-critical relations -> RESTRICT (explicit delete required)
    _replace_fk("wishlists", ["user_id"], "users", ["id"], "fk_wishlists_user_id_users", "RESTRICT")
    _replace_fk("wishlist_filters", ["wishlist_id"], "wishlists", ["id"], "fk_wishlist_filters_wishlist_id_wishlists", "RESTRICT")
    _replace_fk("wishlist_tokens", ["wishlist_id"], "wishlists", ["id"], "fk_wishlist_tokens_wishlist_id_wishlists", "RESTRICT")
    _replace_fk("notifications", ["user_id"], "users", ["id"], "fk_notifications_user_id_users", "RESTRICT")
    _replace_fk("notifications", ["car_listing_id"], "car_listings", ["id"], "fk_notifications_car_listing_id_car_listings", "RESTRICT")
    _replace_fk("account_members", ["account_id"], "accounts", ["id"], "fk_account_members_account_id_accounts", "RESTRICT")
    _replace_fk("account_members", ["user_id"], "users", ["id"], "fk_account_members_user_id_users", "RESTRICT")
    _replace_fk("subscriptions", ["account_id"], "accounts", ["id"], "fk_subscriptions_account_id_accounts", "RESTRICT")


def downgrade() -> None:
    # Keep restrictive behavior on downgrade to avoid reintroducing cascades.
    _replace_fk("wishlists", ["user_id"], "users", ["id"], "fk_wishlists_user_id_users", "RESTRICT")
    _replace_fk("wishlist_filters", ["wishlist_id"], "wishlists", ["id"], "fk_wishlist_filters_wishlist_id_wishlists", "RESTRICT")
    _replace_fk("wishlist_tokens", ["wishlist_id"], "wishlists", ["id"], "fk_wishlist_tokens_wishlist_id_wishlists", "RESTRICT")
    _replace_fk("notifications", ["user_id"], "users", ["id"], "fk_notifications_user_id_users", "RESTRICT")
    _replace_fk("notifications", ["car_listing_id"], "car_listings", ["id"], "fk_notifications_car_listing_id_car_listings", "RESTRICT")
    _replace_fk("account_members", ["account_id"], "accounts", ["id"], "fk_account_members_account_id_accounts", "RESTRICT")
    _replace_fk("account_members", ["user_id"], "users", ["id"], "fk_account_members_user_id_users", "RESTRICT")
    _replace_fk("subscriptions", ["account_id"], "accounts", ["id"], "fk_subscriptions_account_id_accounts", "RESTRICT")
