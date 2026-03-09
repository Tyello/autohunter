"""admin deploy audits

Revision ID: aa12b3c4d5e6
Revises: fase1_007_car_contract
Create Date: 2026-03-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "aa12b3c4d5e6"
down_revision = "fase1_007_car_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_deploy_audits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("operation_id", sa.Text(), nullable=False),
        sa.Column("requested_by_tg_user_id", sa.Integer(), nullable=True),
        sa.Column("requested_by_username", sa.Text(), nullable=True),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("branch", sa.Text(), nullable=True),
        sa.Column("before_commit", sa.Text(), nullable=True),
        sa.Column("after_commit", sa.Text(), nullable=True),
        sa.Column("services_json", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("output_tail", sa.Text(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_deploy_audits_operation_id", "admin_deploy_audits", ["operation_id"], unique=True)
    op.create_index("ix_admin_deploy_audits_status", "admin_deploy_audits", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_admin_deploy_audits_status", table_name="admin_deploy_audits")
    op.drop_index("ix_admin_deploy_audits_operation_id", table_name="admin_deploy_audits")
    op.drop_table("admin_deploy_audits")
