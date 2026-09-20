"""admin kv + alert fields

Revision ID: d1a7c0f6b2aa
Revises: 00667b84d001
Create Date: 2026-01-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d1a7c0f6b2aa"
# Reancorada em 00667b84d001 (que já cria "subscriptions", usada abaixo) em vez
# de ec4a5f769526 diretamente. ec4a5f769526 tinha 3 filhos diretos
# (0009_source_metrics, a branch que leva a 00667b84d001, e esta); um
# depends_on cruzado nesse branchpoint de 3 vias disparava um bug interno do
# Alembic (KeyError no head tracking). Encadear aqui reduz para um branchpoint
# de 2 vias, que já é o padrão usado no resto do histórico.
down_revision: Union[str, Sequence[str], None] = "00667b84d001"
branch_labels: Union[str, Sequence[str], None] = None
# source_states só existe a partir de 0009_source_metrics; sem esta dependência
# explícita, o Alembic pode aplicar este branch antes daquele em um banco novo.
depends_on: Union[str, Sequence[str], None] = "0009_source_metrics"


def upgrade() -> None:
    op.create_table(
        "app_kv",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        """
        create trigger app_kv_updated_at
        before update on app_kv
        for each row
        execute function update_updated_at();
        """
    )

    op.add_column("source_states", sa.Column("last_admin_alert_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("source_states", sa.Column("last_admin_alert_status", sa.Text(), nullable=True))
    op.add_column("source_states", sa.Column("last_admin_alert_error_hash", sa.Text(), nullable=True))

    # proteção adicional no banco: starts_at default now()
    op.alter_column("subscriptions", "starts_at", server_default=sa.text("now()"))


def downgrade() -> None:
    op.alter_column("subscriptions", "starts_at", server_default=None)

    op.drop_column("source_states", "last_admin_alert_error_hash")
    op.drop_column("source_states", "last_admin_alert_status")
    op.drop_column("source_states", "last_admin_alert_at")

    op.execute("drop trigger if exists app_kv_updated_at on app_kv;")
    op.drop_table("app_kv")
