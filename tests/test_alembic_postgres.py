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
