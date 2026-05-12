"""remove legacy plans pro/ultra/paid

Revision ID: 7b9e1c2d3f4a
Revises: 6f7e8d9c0a1b
Create Date: 2026-05-12 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "7b9e1c2d3f4a"
down_revision: Union[str, Sequence[str], None] = "6f7e8d9c0a1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        insert into plans (id, code, name, daily_alert_limit, max_wishlists, is_active, created_at, updated_at)
        values (gen_random_uuid(), 'free', 'Free', 5, 2, true, now(), now())
        on conflict (code) do update set
          name = excluded.name,
          daily_alert_limit = excluded.daily_alert_limit,
          max_wishlists = excluded.max_wishlists,
          is_active = true,
          updated_at = now();
        """
    )
    op.execute(
        """
        insert into plans (id, code, name, daily_alert_limit, max_wishlists, is_active, created_at, updated_at)
        values (gen_random_uuid(), 'premium', 'Premium', 200, 15, true, now(), now())
        on conflict (code) do update set
          name = excluded.name,
          daily_alert_limit = excluded.daily_alert_limit,
          max_wishlists = excluded.max_wishlists,
          is_active = true,
          updated_at = now();
        """
    )

    op.execute(
        """
        update subscriptions s
        set plan_id = p_premium.id
        from plans p_old, plans p_premium
        where s.plan_id = p_old.id
          and p_old.code in ('pro', 'ultra', 'paid')
          and p_premium.code = 'premium';
        """
    )

    op.execute("delete from plans where code in ('pro', 'ultra', 'paid')")


def downgrade() -> None:
    # Não recria planos legados removidos para evitar restaurar oferta comercial descontinuada.
    pass
