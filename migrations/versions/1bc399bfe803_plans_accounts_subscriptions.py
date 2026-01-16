"""plans accounts subscriptions

Revision ID: 00667b84d001
Revises: 00667b84d001
Create Date: 2026-01-16 00:29:28.662046

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '00667b84d001'
down_revision: Union[str, Sequence[str], None] = '8cd5bef4f6b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) plans
    op.create_table(
        "plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("daily_alert_limit", sa.Integer(), nullable=False),
        sa.Column("max_wishlists", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("code", name="ux_plans_code"),
    )
    op.create_index("ix_plans_code", "plans", ["code"], unique=True)

    # 2) accounts
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.Text(), nullable=False, server_default="personal"),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_accounts_type", "accounts", ["type"], unique=False)

    # 3) account_members
    op.create_table(
        "account_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="owner"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("account_id", "user_id", name="ux_account_members_account_user"),
    )
    op.create_index("ix_account_members_user", "account_members", ["user_id"], unique=False)

    # 4) users.account_id
    op.add_column("users", sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_users_account_id", "users", ["account_id"], unique=False)
    op.create_foreign_key(
        "fk_users_account_id",
        "users",
        "accounts",
        ["account_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 5) subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("daily_alert_limit_override", sa.Integer(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_subscriptions_account_status", "subscriptions", ["account_id", "status"], unique=False)

    # 6) seed plans
    op.execute(
        """
        insert into plans (id, code, name, daily_alert_limit, max_wishlists, is_active)
        values
          (gen_random_uuid(), 'free','Free',10,3,true),
          (gen_random_uuid(), 'pro','Pro',50,10,true),
          (gen_random_uuid(), 'ultra','Ultra',200,30,true)
        on conflict (code) do nothing;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_account_status", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_constraint("fk_users_account_id", "users", type_="foreignkey")
    op.drop_index("ix_users_account_id", table_name="users")
    op.drop_column("users", "account_id")

    op.drop_index("ix_account_members_user", table_name="account_members")
    op.drop_table("account_members")

    op.drop_index("ix_accounts_type", table_name="accounts")
    op.drop_table("accounts")

    op.drop_index("ix_plans_code", table_name="plans")
    op.drop_table("plans")

