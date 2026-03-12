from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.wishlists_service import remove_wishlist


def _enable_fk(db) -> None:
    db.execute(text("PRAGMA foreign_keys=ON"))


def test_no_model_fk_uses_cascade_delete() -> None:
    cascades: list[tuple[str, str]] = []
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            if (fk.ondelete or "").upper() == "CASCADE":
                cascades.append((table.name, str(fk.target_fullname)))

    assert cascades == []


def test_no_orm_relationship_uses_delete_cascade() -> None:
    dangerous: list[str] = []

    for mapper in Base.registry.mappers:
        for rel in mapper.relationships:
            cascade_options = {opt.lower() for opt in rel.cascade}
            if "delete" in cascade_options or "delete-orphan" in cascade_options:
                dangerous.append(f"{mapper.class_.__name__}.{rel.key}={sorted(cascade_options)}")

    assert dangerous == []


def test_no_migration_reintroduces_on_delete_cascade() -> None:
    migrations_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    offenders: list[str] = []

    for migration_file in sorted(migrations_dir.glob("*.py")):
        content = migration_file.read_text(encoding="utf-8").upper()
        if "ONDELETE=\"CASCADE\"" in content or "ONDELETE='CASCADE'" in content:
            offenders.append(str(migration_file.relative_to(Path(__file__).resolve().parents[1])))

    assert offenders == []


def test_delete_user_with_wishlist_is_restricted(db):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=123456)
    db.add(user)
    db.flush()
    db.add(Wishlist(user_id=user.id, query="civic", is_active=True))
    db.commit()

    db.delete(user)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_delete_wishlist_with_filters_requires_explicit_cleanup(db):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=999001)
    db.add(user)
    db.flush()

    wishlist = Wishlist(user_id=user.id, query="gol", is_active=True)
    db.add(wishlist)
    db.flush()

    db.add(WishlistFilter(wishlist_id=wishlist.id, field="year", operator="gte", value="2015"))
    db.commit()

    db.delete(wishlist)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_remove_wishlist_service_deletes_children_explicitly(db):
    _enable_fk(db)

    user = User(id=uuid.uuid4(), telegram_chat_id=999002)
    db.add(user)
    db.flush()

    wishlist = Wishlist(user_id=user.id, query="corolla", is_active=True)
    db.add(wishlist)
    db.flush()

    db.add(WishlistFilter(wishlist_id=wishlist.id, field="source", operator="eq", value="olx"))
    db.commit()

    ok, _msg = remove_wishlist(db, user.id, 1)
    assert ok is True
    assert db.query(Wishlist).filter(Wishlist.id == wishlist.id).count() == 0
