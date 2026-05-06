"""normalize public plans to free/premium

Revision ID: 2f4d2d9f8a11
Revises: a1b2c3d4e5f6
Create Date: 2026-05-06 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "2f4d2d9f8a11"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        insert into plans (id, code, name, daily_alert_limit, max_wishlists, is_active)
        values (gen_random_uuid(), 'free', 'Free', 5, 2, true)
        on conflict (code) do update set
          name = excluded.name,
          daily_alert_limit = excluded.daily_alert_limit,
          max_wishlists = excluded.max_wishlists,
          is_active = true;
        """
    )
    op.execute(
        """
        insert into plans (id, code, name, daily_alert_limit, max_wishlists, is_active)
        values (gen_random_uuid(), 'premium', 'Premium', 15, 10, true)
        on conflict (code) do update set
          name = excluded.name,
          daily_alert_limit = excluded.daily_alert_limit,
          max_wishlists = excluded.max_wishlists,
          is_active = true;
        """
    )

    op.execute(
        """
        update subscriptions s
        set plan_id = p_premium.id
        from plans p_old, plans p_premium
        where s.plan_id = p_old.id
          and p_old.code in ('pro', 'ultra', 'paid')
          and p_premium.code = 'premium'
          and s.status = 'active';
        """
    )

    op.execute("update plans set is_active = false where code in ('pro', 'ultra', 'paid')")


def downgrade() -> None:
    # Downgrade parcial: reativa planos legados sem reverter subscriptions migradas.
    op.execute("update plans set is_active = true where code in ('pro', 'ultra', 'paid')")
