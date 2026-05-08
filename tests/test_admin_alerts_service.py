from __future__ import annotations

from app.services import admin_alerts_service as svc


class _Resp:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Session:
    def __init__(self, resp: _Resp):
        self._resp = resp

    def post(self, *args, **kwargs):
        return self._resp


def test_send_admin_text_with_report_success(monkeypatch):
    monkeypatch.setattr(svc.settings, "telegram_bot_token", "token")
    monkeypatch.setattr(svc.settings, "autohunter_admin_alert_chats", "123")
    monkeypatch.setattr(svc.settings, "autohunter_admins", None)
    monkeypatch.setattr(svc, "get_shared_session", lambda _: _Session(_Resp(200, {"ok": True})))

    report = svc.send_admin_text_with_report("hello")

    assert report["attempted"] == 1
    assert report["sent"] == 1
    assert report["failed"] == 0


def test_send_admin_text_with_report_telegram_forbidden(monkeypatch):
    monkeypatch.setattr(svc.settings, "telegram_bot_token", "token")
    monkeypatch.setattr(svc.settings, "autohunter_admin_alert_chats", "123")
    monkeypatch.setattr(svc, "get_shared_session", lambda _: _Session(_Resp(403, {"ok": False, "description": "Forbidden"}, text='{"ok":false}')))

    report = svc.send_admin_text_with_report("hello")

    assert report["attempted"] == 1
    assert report["sent"] == 0
    assert report["failed"] == 1


def test_send_admin_text_with_report_invalid_json_on_200(monkeypatch):
    monkeypatch.setattr(svc.settings, "telegram_bot_token", "token")
    monkeypatch.setattr(svc.settings, "autohunter_admin_alert_chats", "123")
    monkeypatch.setattr(svc, "get_shared_session", lambda _: _Session(_Resp(200, ValueError("invalid"), text="not-json")))

    report = svc.send_admin_text_with_report("hello")

    assert report["attempted"] == 1
    assert report["sent"] == 0
    assert report["failed"] == 1


def test_send_admin_text_with_report_without_admin_chats(monkeypatch):
    monkeypatch.setattr(svc.settings, "telegram_bot_token", "token")
    monkeypatch.setattr(svc.settings, "autohunter_admin_alert_chats", None)
    monkeypatch.setattr(svc.settings, "autohunter_admins", None)

    report = svc.send_admin_text_with_report("hello")

    assert report["attempted"] == 0
    assert report["sent"] == 0
    assert report["failed"] == 0


def test_send_admin_text_keeps_compat_wrapper(monkeypatch):
    called = []

    def _fake(_):
        called.append(True)
        return {"sent": 0}

    monkeypatch.setattr(svc, "send_admin_text_with_report", _fake)
    svc.send_admin_text("hello")
    assert called == [True]
