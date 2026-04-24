from __future__ import annotations

import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

from app.bot import handlers_admin
from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.scrape_job import ScrapeJob
from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.models.system_log import SystemLog
from app.models.user import User
from app.models.wishlist import Wishlist


class _Msg:
    def __init__(self):
        self.sent: list[str] = []

    async def reply_text(self, txt, **_kwargs):
        self.sent.append(txt)


class _Update:
    def __init__(self, chat_id=777):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.message = _Msg()


def _run_health(monkeypatch, update, args=None):
    captured = {"text": ""}

    async def _fake_reply_chunked(_update, text, max_len=3600):
        captured["text"] = text

    monkeypatch.setattr(handlers_admin, "_reply_chunked", _fake_reply_chunked)
    monkeypatch.setattr(handlers_admin, "sanitize_for_telegram", lambda t: t)
    asyncio.run(handlers_admin._admin_health(update, raw_args=args or []))
    return captured["text"]


def _mk_user_and_listing(db):
    user = User(id=uuid.uuid4(), telegram_chat_id=5511, username="admin-health", is_active=True)
    db.add(user)
    wishlist = Wishlist(id=uuid.uuid4(), user_id=user.id, query="civic", is_active=True)
    db.add(wishlist)
    listing = CarListing(
        id=uuid.uuid4(),
        source="olx",
        external_id="OLX-1",
        title="Civic",
        url="https://example.com/1",
        price=100000,
        location="São Paulo, SP",
        currency="BRL",
    )
    db.add(listing)
    db.commit()
    return user, wishlist, listing


def test_admin_health_blocks_non_admin_without_opening_db(monkeypatch):
    update = _Update(chat_id=999)
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)

    called = {"db": False}

    class _SessionFail:
        def __enter__(self):
            called["db"] = True
            raise AssertionError("DB should not open for unauthorized /admin health")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionFail())

    asyncio.run(handlers_admin._admin_health(update, raw_args=[]))
    assert called["db"] is False
    assert update.message.sent and "Sem permissão" in update.message.sent[-1]


def test_admin_health_authorized_includes_heartbeat_not_stale(monkeypatch, db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=2)))
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    text = _run_health(monkeypatch, _Update(), [])

    assert "Scheduler heartbeat:" in text
    assert "⚠️stale" not in text


def test_admin_health_marks_stale_heartbeat(monkeypatch, db):
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=120)))
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    text = _run_health(monkeypatch, _Update(), [])

    assert "Scheduler heartbeat:" in text
    assert "⚠️stale" in text


def test_admin_health_stale_filters_and_sections(monkeypatch, db):
    now = datetime.now(timezone.utc)
    old = now - timedelta(minutes=500)
    user, wishlist, listing = _mk_user_and_listing(db)
    # enabled + wishlist -> stale
    db.add(SourceConfig(source="mercadolivre", is_enabled=True, sched_minutes=60))
    db.add(SourceRun(source="mercadolivre", kind="scheduler", status="success", created_at=old))

    # disabled should not be stale critical
    db.add(SourceConfig(source="turboclass", is_enabled=False, sched_minutes=60))
    db.add(SourceRun(source="turboclass", kind="scheduler", status="success", created_at=old))

    # auxiliary/not implemented should not be stale critical
    db.add(SourceConfig(source="turboclass_vendidos", is_enabled=False, sched_minutes=60))
    db.add(SourceRun(source="turboclass_vendidos", kind="scheduler", status="success", created_at=old))

    # paused/backoff + webmotors anti-bot hint
    db.add(SourceConfig(source="webmotors", is_enabled=True, sched_minutes=60))
    db.add(SourceRun(source="webmotors", kind="scheduler", status="blocked", created_at=old, error="perimeterx"))
    db.add(SourceState(source="webmotors", next_allowed_at=now + timedelta(minutes=180), last_status="blocked"))

    # queue snapshots
    db.add_all([
        ScrapeJob(source="olx", queue="default", status="queued", run_at=now),
        ScrapeJob(source="olx", queue="default", status="running", run_at=now, started_at=now - timedelta(minutes=1)),
        ScrapeJob(source="olx", queue="default", status="failed", run_at=now),
    ])
    db.add_all([
        Notification(user_id=user.id, wishlist_id=wishlist.id, car_listing_id=listing.id, status="queued"),
        Notification(user_id=user.id, wishlist_id=wishlist.id, car_listing_id=listing.id, status="sent"),
    ])

    # failures order
    db.add(SourceRun(source="olx", kind="scheduler", status="error", created_at=now - timedelta(minutes=10), error="err-new"))
    db.add(SourceRun(source="olx", kind="scheduler", status="error", created_at=now - timedelta(minutes=40), error="err-old"))
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    text = _run_health(monkeypatch, _Update(), ["verbose"])

    assert "Sources stale:" in text
    assert "- mercadolivre: stale" in text
    assert "- turboclass: stale" not in text
    assert "- turboclass_vendidos: stale" not in text
    assert "Sources disabled:" in text and "turboclass: disabled" in text
    assert "Sources paused (backoff/throttle):" in text
    assert "webmotors" in text and "anti-bot" in text
    assert "scrape_jobs:" in text and "queued=" in text and "running=" in text
    assert "notifications:" in text and "queued=" in text and "sent=" in text
    assert text.index("err-new") < text.index("err-old")


def test_admin_health_auxiliary_source_is_not_stale_critical(monkeypatch, db):
    now = datetime.now(timezone.utc)
    old = now - timedelta(minutes=500)
    db.add(SourceConfig(source="turboclass_vendidos", is_enabled=True, sched_minutes=60))
    db.add(SourceRun(source="turboclass_vendidos", kind="scheduler", status="success", created_at=old))
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    text = _run_health(monkeypatch, _Update(), ["verbose"])

    assert "- turboclass_vendidos: stale" not in text
    assert "Sources auxiliary/not_implemented:" in text
    assert "turboclass_vendidos" in text


def test_admin_health_verbose_uses_chunking(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    now = datetime.now(timezone.utc)
    for i in range(30):
        db.add(SourceRun(source="olx", kind="scheduler", status="error", created_at=now - timedelta(minutes=i), error=f"boom-{i}"))
    db.commit()

    chunks: list[str] = []

    async def _capture_reply(update, text, max_len=3600):
        for c in handlers_admin._chunk_lines(text, max_len=200):
            chunks.append(c)
            await update.message.reply_text(c)

    monkeypatch.setattr(handlers_admin, "_reply_chunked", _capture_reply)
    monkeypatch.setattr(handlers_admin, "sanitize_for_telegram", lambda t: t)

    update = _Update()
    asyncio.run(handlers_admin._admin_health(update, raw_args=["verbose"]))

    assert len(chunks) >= 2
    assert all(len(c) <= 200 for c in chunks)
