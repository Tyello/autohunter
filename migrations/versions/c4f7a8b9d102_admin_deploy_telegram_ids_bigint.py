"""admin deploy telegram ids bigint

Revision ID: c4f7a8b9d102
Revises: aa12b3c4d5e6
Create Date: 2026-03-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4f7a8b9d102"
down_revision = "aa12b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "admin_deploy_audits",
        "requested_by_tg_user_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
        postgresql_using="requested_by_tg_user_id::bigint",
    )
    op.alter_column(
        "admin_deploy_audits",
        "chat_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        postgresql_using="chat_id::bigint",
    )


def downgrade() -> None:
    op.alter_column(
        "admin_deploy_audits",
        "chat_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="chat_id::integer",
    )
    op.alter_column(
        "admin_deploy_audits",
        "requested_by_tg_user_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="requested_by_tg_user_id::integer",
    )
