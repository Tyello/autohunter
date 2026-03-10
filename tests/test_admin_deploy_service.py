from __future__ import annotations

from types import SimpleNamespace
from datetime import timedelta, timezone, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql.sqltypes import BigInteger

from app.db.base import Base
from app.models.admin_deploy_audit import AdminDeployAudit
from app.services.admin_deploy_service import AdminDeployService, DeployActor, _classify_home_access_error


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[AdminDeployAudit.__table__])
    return sessionmaker(bind=engine)()


def _actor(chat_id=10, user_id=20):
    return DeployActor(chat_id=chat_id, tg_user_id=user_id, username="admin")


def _allow(monkeypatch):
    monkeypatch.setattr("app.services.admin_deploy_service.settings", SimpleNamespace(
        admin_deploy_pending_ttl_seconds=120,
        admin_deploy_rate_limit_seconds=300,
        admin_deploy_wrapper_timeout_seconds=180,
        admin_deploy_output_max_chars=60,
        admin_deploy_wrapper_path="/wrapper",
        admin_deploy_use_sudo=False,
        autohunter_admin_user_ids="20",
        autohunter_admin_chat_ids="10",
        autohunter_admins="10",
    ))


def test_access_denied_non_admin_user(monkeypatch):
    _allow(monkeypatch)
    svc = AdminDeployService(_db())
    ok, _ = svc.is_allowed(_actor(user_id=999))
    assert not ok


def test_access_denied_non_admin_chat(monkeypatch):
    _allow(monkeypatch)
    svc = AdminDeployService(_db())
    ok, _ = svc.is_allowed(_actor(chat_id=999))
    assert not ok


def test_confirmation_expired(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(svc, "_run_preflight", lambda: {"branch": "main", "commit": "abc", "working_tree": "clean", "remote_ok": True, "remote_diff": "0 0"})
    op = svc.request_deploy(_actor())["operation_id"]
    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    import pytest
    with pytest.raises(ValueError, match="expirada"):
        import asyncio
        asyncio.run(svc.confirm_deploy(_actor(), op))


def test_rate_limit(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(svc, "_run_preflight", lambda: {"branch": "main", "commit": "abc", "working_tree": "clean", "remote_ok": True, "remote_diff": "0 0"})
    svc.request_deploy(_actor())
    import pytest
    with pytest.raises(ValueError, match="Rate limit"):
        svc.request_deploy(_actor())


def test_lock_global(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(svc, "_run_preflight", lambda: {"branch": "main", "commit": "abc", "working_tree": "clean", "remote_ok": True, "remote_diff": "0 0"})
    op = svc.request_deploy(_actor())["operation_id"]
    svc._lock = SimpleNamespace(locked=lambda: True)  # type: ignore[assignment]
    import pytest, asyncio
    with pytest.raises(ValueError, match="andamento"):
        asyncio.run(svc.confirm_deploy(_actor(), op))


def test_deploy_success(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(svc, "_run_preflight", lambda: {"branch": "main", "commit": "abc", "working_tree": "clean", "remote_ok": True, "remote_diff": "0 0"})
    op = svc.request_deploy(_actor())["operation_id"]

    async def _ok(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout='{"ok": true, "status": "success", "before_commit": "abc", "after_commit": "def", "branch": "main", "services": [{"name":"x","status":"active"}]}', stderr="")
    monkeypatch.setattr("app.services.admin_deploy_service.asyncio.to_thread", lambda fn, *a, **k: _ok())

    import asyncio
    out = asyncio.run(svc.confirm_deploy(_actor(), op))
    assert out["ok"] is True


def test_fail_git_pull(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(svc, "_run_preflight", lambda: {"branch": "main", "commit": "abc", "working_tree": "clean", "remote_ok": True, "remote_diff": "0 0"})
    op = svc.request_deploy(_actor())["operation_id"]

    async def _bad(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout='{"ok": false, "error_type": "git_pull", "error_message": "failed"}', stderr="err")
    monkeypatch.setattr("app.services.admin_deploy_service.asyncio.to_thread", lambda fn, *a, **k: _bad())

    import asyncio
    out = asyncio.run(svc.confirm_deploy(_actor(), op))
    assert out["ok"] is False


def test_fail_service_restart(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(svc, "_run_preflight", lambda: {"branch": "main", "commit": "abc", "working_tree": "clean", "remote_ok": True, "remote_diff": "0 0"})
    op = svc.request_deploy(_actor())["operation_id"]

    async def _bad(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout='{"ok": false, "error_type": "service_restart", "error_message": "svc"}', stderr="err")
    monkeypatch.setattr("app.services.admin_deploy_service.asyncio.to_thread", lambda fn, *a, **k: _bad())

    import asyncio
    out = asyncio.run(svc.confirm_deploy(_actor(), op))
    assert out["ok"] is False


def test_output_truncation_and_audit_persistence(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(svc, "_run_preflight", lambda: {"branch": "main", "commit": "abc", "working_tree": "clean", "remote_ok": True, "remote_diff": "0 0"})
    op = svc.request_deploy(_actor())["operation_id"]

    async def _bad(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout='{"ok": false, "error_type": "git_pull", "error_message": "x"}', stderr="y" * 500)
    monkeypatch.setattr("app.services.admin_deploy_service.asyncio.to_thread", lambda fn, *a, **k: _bad())

    import asyncio
    out = asyncio.run(svc.confirm_deploy(_actor(), op))
    assert "truncated" in out["output_tail"]
    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    assert row is not None
    assert row.status == "failed"
    assert row.output_tail


def test_request_deploy_accepts_large_telegram_ids(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(svc, "_run_preflight", lambda: {"branch": "main", "commit": "abc", "working_tree": "clean", "remote_ok": True, "remote_diff": "0 0"})

    large_id = 5_410_199_985
    op = svc.request_deploy(_actor(chat_id=large_id, user_id=large_id))["operation_id"]

    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    assert row is not None
    assert row.requested_by_tg_user_id == large_id
    assert row.chat_id == large_id


def test_admin_deploy_audit_telegram_columns_are_bigint():
    assert isinstance(AdminDeployAudit.__table__.c.requested_by_tg_user_id.type, BigInteger)
    assert isinstance(AdminDeployAudit.__table__.c.chat_id.type, BigInteger)


def test_is_allowed_with_large_actor_ids(monkeypatch):
    large_id = 5_410_199_985
    monkeypatch.setattr("app.services.admin_deploy_service.settings", SimpleNamespace(
        admin_deploy_pending_ttl_seconds=120,
        admin_deploy_rate_limit_seconds=300,
        admin_deploy_wrapper_timeout_seconds=180,
        admin_deploy_output_max_chars=60,
        admin_deploy_wrapper_path="/wrapper",
        admin_deploy_use_sudo=False,
        autohunter_admin_user_ids=str(large_id),
        autohunter_admin_chat_ids=str(large_id),
        autohunter_admins=str(large_id),
    ))

    svc = AdminDeployService(_db())
    ok, reason = svc.is_allowed(_actor(chat_id=large_id, user_id=large_id))
    assert ok is True
    assert reason is None




def test_classify_home_access_error_known_hosts():
    mapped = _classify_home_access_error('git@github.com: /home/autohunter/.ssh/known_hosts: Permission denied')
    assert mapped is not None
    error_type, message = mapped
    assert error_type == "protect_home_blocked"
    assert "autohunter-bot.service" in message


def test_classify_home_access_error_git_ignore():
    mapped = _classify_home_access_error('fatal: could not open /home/autohunter/.config/git/ignore: Permission denied')
    assert mapped is not None
    error_type, message = mapped
    assert error_type == "home_not_accessible_from_service"
    assert "HOME" in message

def test_preflight_maps_no_new_privileges(monkeypatch):
    monkeypatch.setattr("app.services.admin_deploy_service.settings", SimpleNamespace(
        admin_deploy_pending_ttl_seconds=120,
        admin_deploy_rate_limit_seconds=300,
        admin_deploy_wrapper_timeout_seconds=180,
        admin_deploy_output_max_chars=60,
        admin_deploy_wrapper_path="/wrapper",
        admin_deploy_use_sudo=True,
        autohunter_admin_user_ids="20",
        autohunter_admin_chat_ids="10",
        autohunter_admins="10",
    ))
    svc = AdminDeployService(_db())

    def _fake_run(*args, **kwargs):
        if args[:2] == ("sudo", "-n"):
            return 1, "", 'sudo: The "no new privileges" flag is set, which prevents sudo from running as root.'
        return 0, "", ""

    monkeypatch.setattr("app.services.admin_deploy_service.subprocess.run", lambda a, cwd, capture_output, text, timeout, env=None: SimpleNamespace(returncode=_fake_run(*a, timeout=timeout)[0], stdout=_fake_run(*a, timeout=timeout)[1], stderr=_fake_run(*a, timeout=timeout)[2]))
    monkeypatch.setattr("app.services.admin_deploy_service.Path.exists", lambda self: True)
    monkeypatch.setattr("app.services.admin_deploy_service.Path.is_file", lambda self: True)
    monkeypatch.setattr("app.services.admin_deploy_service.Path.stat", lambda self: SimpleNamespace(st_mode=0o755))

    preflight = svc._run_preflight()
    assert preflight["privilege_ready"] is False
    assert preflight["privilege_error_type"] == "no_new_privileges"


def test_confirm_blocked_when_preflight_privilege_not_ready(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(
        svc,
        "_run_preflight",
        lambda: {
            "branch": "main",
            "commit": "abc",
            "working_tree": "clean",
            "remote_ok": True,
            "remote_diff": "0 0",
            "privilege_ready": False,
            "privilege_error_type": "no_new_privileges",
            "privilege_error_message": "blocked",
        },
    )
    op = svc.request_deploy(_actor())["operation_id"]

    import pytest, asyncio
    with pytest.raises(ValueError, match="NoNewPrivileges"):
        asyncio.run(svc.confirm_deploy(_actor(), op))

    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    assert row is not None
    assert row.status == "blocked"


def test_request_deploy_persists_privilege_block_in_audit(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(
        svc,
        "_run_preflight",
        lambda: {
            "branch": "main",
            "commit": "abc",
            "working_tree": "clean",
            "remote_ok": True,
            "remote_diff": "0 0",
            "privilege_ready": False,
            "privilege_error_type": "no_new_privileges",
            "privilege_error_message": "Serviço do bot está com NoNewPrivileges ativo.",
        },
    )

    op = svc.request_deploy(_actor())["operation_id"]
    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    assert row is not None
    assert row.summary == "preflight_blocked_privilege"
    assert row.error_type == "privilege_no_new_privileges"
    assert "NoNewPrivileges" in (row.error_message or "")


def test_request_deploy_persists_dirty_tree_block(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(
        svc,
        "_run_preflight",
        lambda: {
            "branch": "main",
            "commit": "abc",
            "working_tree": "dirty",
            "remote_ok": True,
            "remote_diff": "0 0",
            "privilege_ready": True,
        },
    )

    op = svc.request_deploy(_actor())["operation_id"]
    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    assert row is not None
    assert row.summary == "preflight_blocked_dirty_tree"
    assert row.error_type == "working_tree_dirty"


def test_confirm_blocked_when_preflight_dirty_tree(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(
        svc,
        "_run_preflight",
        lambda: {
            "branch": "main",
            "commit": "abc",
            "working_tree": "dirty",
            "remote_ok": True,
            "remote_diff": "0 0",
            "privilege_ready": True,
        },
    )
    op = svc.request_deploy(_actor())["operation_id"]

    import pytest, asyncio
    with pytest.raises(ValueError, match="working tree dirty"):
        asyncio.run(svc.confirm_deploy(_actor(), op))

    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    assert row is not None
    assert row.status == "blocked"
    assert row.summary == "blocked_by_preflight_dirty_tree"


def test_confirm_maps_known_hosts_permission_denied_to_operational_error(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(svc, "_run_preflight", lambda: {"branch": "main", "commit": "abc", "working_tree": "clean", "remote_ok": True, "remote_diff": "0 0"})
    op = svc.request_deploy(_actor())["operation_id"]

    async def _bad(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout='{"ok": false}', stderr='fatal: /home/autohunter/.ssh/known_hosts: Permission denied')

    monkeypatch.setattr("app.services.admin_deploy_service.asyncio.to_thread", lambda fn, *a, **k: _bad())

    import asyncio
    out = asyncio.run(svc.confirm_deploy(_actor(), op))
    assert out["ok"] is False

    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    assert row is not None
    assert row.error_type == "protect_home_blocked"
    assert "autohunter-bot.service" in (row.error_message or "")


def test_confirm_maps_git_ignore_permission_denied_to_operational_error(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(svc, "_run_preflight", lambda: {"branch": "main", "commit": "abc", "working_tree": "clean", "remote_ok": True, "remote_diff": "0 0"})
    op = svc.request_deploy(_actor())["operation_id"]

    async def _bad(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout='{"ok": false}', stderr='fatal: could not open /home/autohunter/.config/git/ignore: Permission denied')

    monkeypatch.setattr("app.services.admin_deploy_service.asyncio.to_thread", lambda fn, *a, **k: _bad())

    import asyncio
    out = asyncio.run(svc.confirm_deploy(_actor(), op))
    assert out["ok"] is False

    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    assert row is not None
    assert row.error_type == "home_not_accessible_from_service"
    assert "HOME" in (row.error_message or "")


def test_preflight_sets_explicit_home_and_xdg(monkeypatch):
    monkeypatch.setattr("app.services.admin_deploy_service.settings", SimpleNamespace(
        admin_deploy_pending_ttl_seconds=120,
        admin_deploy_rate_limit_seconds=300,
        admin_deploy_wrapper_timeout_seconds=180,
        admin_deploy_output_max_chars=60,
        admin_deploy_wrapper_path="/wrapper",
        admin_deploy_use_sudo=False,
        admin_deploy_app_home="/home/autohunter",
        autohunter_admin_user_ids="20",
        autohunter_admin_chat_ids="10",
        autohunter_admins="10",
    ))
    svc = AdminDeployService(_db())
    envs = []

    def _fake_run(args, cwd, capture_output, text, timeout, env=None):
        envs.append(env or {})
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.services.admin_deploy_service.subprocess.run", _fake_run)
    monkeypatch.setattr("app.services.admin_deploy_service.Path.exists", lambda self: True)
    monkeypatch.setattr("app.services.admin_deploy_service.Path.is_file", lambda self: True)
    monkeypatch.setattr("app.services.admin_deploy_service.Path.stat", lambda self: SimpleNamespace(st_mode=0o755))

    svc._run_preflight()

    assert envs
    assert envs[0].get("HOME") == "/home/autohunter"
    assert envs[0].get("XDG_CONFIG_HOME") == "/home/autohunter/.config"


def test_confirm_blocked_when_preflight_remote_unreachable(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(
        svc,
        "_run_preflight",
        lambda: {
            "branch": "main",
            "commit": "abc",
            "working_tree": "clean",
            "remote_ok": False,
            "remote_diff": "indisponível",
            "privilege_ready": True,
        },
    )
    op = svc.request_deploy(_actor())["operation_id"]

    import pytest, asyncio
    with pytest.raises(ValueError, match="remote_ok=no"):
        asyncio.run(svc.confirm_deploy(_actor(), op))

    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    assert row is not None
    assert row.status == "blocked"
    assert row.summary == "blocked_by_preflight_remote"


def test_confirm_blocked_when_preflight_host_structural_error(monkeypatch):
    _allow(monkeypatch)
    db = _db()
    svc = AdminDeployService(db)
    monkeypatch.setattr(
        svc,
        "_run_preflight",
        lambda: {
            "branch": "unknown",
            "commit": "unknown",
            "working_tree": "clean",
            "remote_ok": True,
            "remote_diff": "0 0",
            "privilege_ready": True,
        },
    )
    op = svc.request_deploy(_actor())["operation_id"]

    import pytest, asyncio
    with pytest.raises(ValueError, match="erro estrutural do host"):
        asyncio.run(svc.confirm_deploy(_actor(), op))

    row = db.query(AdminDeployAudit).filter(AdminDeployAudit.operation_id == op).first()
    assert row is not None
    assert row.status == "blocked"
    assert row.summary == "blocked_by_preflight_host"


def test_deploy_status_includes_last_deploy_timestamp_and_noop(monkeypatch):
    _allow(monkeypatch)
    db = _db()

    now = datetime.now(timezone.utc)
    row = AdminDeployAudit(
        operation_id="abc123noop",
        requested_by_tg_user_id=20,
        requested_by_username="admin",
        chat_id=10,
        requested_at=now - timedelta(minutes=2),
        confirmed_at=now - timedelta(minutes=2),
        started_at=now - timedelta(minutes=2),
        finished_at=now - timedelta(minutes=1),
        status="succeeded",
        branch="main",
        before_commit="same",
        after_commit="same",
        summary="ok",
    )
    db.add(row)
    db.commit()

    svc = AdminDeployService(db)
    out = svc.deploy_status()
    assert out["status"] == "noop"
    assert out["last"] is not None
    assert out["last"].finished_at is not None
