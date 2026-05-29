from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.services.db_runtime_safety_service import (
    POSTGRES_ROLE_WARNING,
    check_database_runtime_role,
    detect_database_url_username,
)


MIGRATION = "5c8f1a2b3d4e"
PREVIOUS = "e7a1c9f2b4d3"
PROTECTED_TABLES = {
    "users",
    "wishlists",
    "wishlist_filters",
    "wishlist_tokens",
    "wishlist_tracked_listings",
    "wishlist_listing_activity",
    "notifications",
    "account_members",
    "user_digest_preferences",
}


def _migration_sql() -> str:
    return (Path(__file__).resolve().parents[1] / "migrations" / "versions" / "5c8f1a2b3d4e_core_data_delete_guardrails.py").read_text(
        encoding="utf-8"
    )


def test_guardrail_migration_lists_all_core_tables() -> None:
    sql = _migration_sql()
    for table in PROTECTED_TABLES:
        assert f'"{table}"' in sql
    assert "prevent_core_data_delete_without_guard" in sql
    assert "BEFORE DELETE" in sql
    assert "BEFORE TRUNCATE" in sql
    assert "app.allow_core_data_delete" in sql


def test_detect_database_url_username_masks_nothing_and_handles_postgres() -> None:
    assert detect_database_url_username("postgresql://postgres:secret@example.com/db") == "postgres"
    assert detect_database_url_username("postgresql://autohunter_app:secret@example.com/db") == "autohunter_app"
    assert detect_database_url_username("sqlite+pysqlite:///tmp/test.db") is None


def test_runtime_role_check_warns_when_url_user_is_postgres_on_non_postgres(db, monkeypatch) -> None:
    monkeypatch.setattr("app.services.db_runtime_safety_service.settings.database_url", "postgresql://postgres:secret@localhost/db")
    out = check_database_runtime_role(db)
    assert out.status == "warning"
    assert out.role == "postgres"
    assert out.warning == POSTGRES_ROLE_WARNING



def _alembic_config(db_url: str) -> Config:
    cfg = Config("alembic.ini")
    # migrations/env.py reads settings.database_url, so keep env in sync too.
    os.environ["DATABASE_URL"] = db_url
    from app.core.settings import settings

    settings.database_url = db_url
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _assert_guard_blocks(conn, sql: str) -> None:
    with pytest.raises(DBAPIError) as excinfo:
        conn.execute(text(sql))
    message = str(excinfo.value)
    assert "Blocked" in message
    assert "app.allow_core_data_delete" in message


@pytest.mark.postgres
def test_postgres_delete_truncate_breakglass_insert_update_and_downgrade() -> None:
    db_url = os.environ["TEST_DATABASE_URL"]
    cfg = _alembic_config(db_url)
    engine = create_engine(db_url)

    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                """
                insert into users (id, telegram_chat_id, username, is_active, plan, created_at, updated_at)
                values (gen_random_uuid(), 920000001, 'guard-user', true, 'free', now(), now())
                returning id
                """
            )
        ).scalar_one()
        wishlist_id = conn.execute(
            text(
                """
                insert into wishlists (id, user_id, query, is_active, include_auctions, created_at, updated_at)
                values (gen_random_uuid(), :user_id, 'civic', true, false, now(), now())
                returning id
                """
            ),
            {"user_id": user_id},
        ).scalar_one()
        conn.execute(text("update users set username='guard-user-updated' where id=:user_id"), {"user_id": user_id})
        assert conn.execute(text("select username from users where id=:user_id"), {"user_id": user_id}).scalar_one() == "guard-user-updated"

    with engine.connect() as conn:
        tx = conn.begin()
        _assert_guard_blocks(conn, "delete from users where telegram_chat_id = 920000001")
        tx.rollback()

        tx = conn.begin()
        _assert_guard_blocks(conn, "delete from wishlists where id = '%s'" % wishlist_id)
        tx.rollback()

        tx = conn.begin()
        _assert_guard_blocks(conn, "truncate table users cascade")
        tx.rollback()

    with engine.begin() as conn:
        conn.execute(text("set local app.allow_core_data_delete = 'on'"))
        deleted = conn.execute(text("delete from wishlists where id=:wishlist_id"), {"wishlist_id": wishlist_id}).rowcount
        assert deleted == 1
        deleted = conn.execute(text("delete from users where id=:user_id"), {"user_id": user_id}).rowcount
        assert deleted == 1

    command.downgrade(cfg, PREVIOUS)
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                """
                insert into users (id, telegram_chat_id, username, is_active, plan, created_at, updated_at)
                values (gen_random_uuid(), 920000002, 'unguarded-user', true, 'free', now(), now())
                returning id
                """
            )
        ).scalar_one()
        deleted = conn.execute(text("delete from users where id=:user_id"), {"user_id": user_id}).rowcount
        assert deleted == 1

    command.upgrade(cfg, "head")
