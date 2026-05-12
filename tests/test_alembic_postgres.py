from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


pytestmark = pytest.mark.postgres


def _alembic_config() -> Config:
    db_url = os.environ["TEST_DATABASE_URL"]
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_alembic_upgrade_and_downgrade_on_postgres() -> None:
    cfg = _alembic_config()
    db_url = cfg.get_main_option("sqlalchemy.url")

    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version

    command.downgrade(cfg, "base")


def test_migration_remaps_legacy_plan_subscriptions_to_premium() -> None:
    cfg = _alembic_config()
    db_url = cfg.get_main_option("sqlalchemy.url")

    command.downgrade(cfg, "6f7e8d9c0a1b")

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("""
            insert into plans (id, code, name, daily_alert_limit, max_wishlists, is_active, created_at, updated_at)
            values
              (gen_random_uuid(), 'pro', 'Pro', 50, 10, true, now(), now()),
              (gen_random_uuid(), 'ultra', 'Ultra', 200, 30, true, now(), now())
            on conflict (code) do nothing
        """))
        conn.execute(text("""
            insert into accounts (id, type, name, is_active, created_at, updated_at)
            values (gen_random_uuid(), 'personal', 'legacy-account', true, now(), now())
        """))
        account_id = conn.execute(text("select id from accounts where name='legacy-account' order by created_at desc limit 1")).scalar_one()
        pro_id = conn.execute(text("select id from plans where code='pro'")).scalar_one()
        conn.execute(text("""
            insert into subscriptions (id, account_id, plan_id, status, source, starts_at, created_at, updated_at)
            values (gen_random_uuid(), :account_id, :plan_id, 'active', 'test', now(), now(), now())
        """), {"account_id": account_id, "plan_id": pro_id})

    command.upgrade(cfg, "7b9e1c2d3f4a")

    with engine.connect() as conn:
        premium_id = conn.execute(text("select id from plans where code='premium'")).scalar_one()
        sub_plan_id = conn.execute(text("""
            select s.plan_id
            from subscriptions s
            join accounts a on a.id = s.account_id
            where a.name='legacy-account'
            order by s.created_at desc
            limit 1
        """)).scalar_one()
        assert sub_plan_id == premium_id
        legacy_count = conn.execute(text("select count(*) from plans where code in ('pro','ultra','paid')")).scalar_one()
        assert legacy_count == 0

    command.downgrade(cfg, "base")
