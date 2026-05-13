import asyncio
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta

import pytest

from app.bot import admin_handlers_deploy
from app.models.admin_deploy_audit import AdminDeployAudit


class DummyMsg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text):
        self.sent.append(text)


def test_deploy_history_renders(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(AdminDeployAudit(operation_id="op1", chat_id=1, requested_at=now - timedelta(minutes=2), started_at=now - timedelta(minutes=2), finished_at=now - timedelta(minutes=1), status="succeeded", branch="main", before_commit="a", after_commit="b", services_json={"bot": "ok"}, summary="done"))
    db.add(AdminDeployAudit(operation_id="op2", chat_id=1, requested_at=now - timedelta(minutes=1), started_at=now - timedelta(minutes=1), finished_at=now, status="failed", branch="main", before_commit="b", after_commit="c", services_json=["api"], error_message="boom", summary="err"))
    db.commit()

    monkeypatch.setattr(admin_handlers_deploy, "SessionLocal", lambda: db)
    u = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_user=SimpleNamespace(id=1, username="u"), message=DummyMsg())
    asyncio.run(admin_handlers_deploy.admin_deploy(u, ["history", "5"], fmt_dt=lambda d: d.strftime("%Y-%m-%d %H:%M") if d else "-"))
    out = "\n".join(u.message.sent)
    assert "Deploy history" in out
    assert "succeeded" in out
    assert "failed" in out
    assert "serviços=bot" in out or "serviços=api" in out


def test_deploy_status_includes_last_deploy(db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(AdminDeployAudit(operation_id="ok", chat_id=1, requested_at=now - timedelta(minutes=3), started_at=now - timedelta(minutes=3), finished_at=now - timedelta(minutes=2), status="succeeded", branch="main", before_commit="a1", after_commit="a2", summary="ok"))
    db.add(AdminDeployAudit(operation_id="bad", chat_id=1, requested_at=now - timedelta(minutes=1), started_at=now - timedelta(minutes=1), finished_at=now, status="failed", branch="main", before_commit="a2", after_commit="a3", error_type="exit_1", error_message="x", summary="err"))
    db.commit()
    monkeypatch.setattr(admin_handlers_deploy, "SessionLocal", lambda: db)
    u = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_user=SimpleNamespace(id=1, username="u"), message=DummyMsg())
    asyncio.run(admin_handlers_deploy.admin_deploy(u, ["status"], fmt_dt=lambda d: d.strftime("%Y-%m-%d %H:%M") if d else "-"))
    out = "\n".join(u.message.sent)
    assert "Último deploy" in out
    assert "Última falha" in out
