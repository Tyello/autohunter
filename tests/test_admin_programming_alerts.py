from __future__ import annotations

import app.services.admin_programming_alerts as mod


def _reset_throttle():
    mod._LAST_SENT.clear()


def test_alerts_for_known_bug_type(monkeypatch):
    _reset_throttle()
    monkeypatch.setattr(mod.settings, "admin_programming_errors_enabled", True)
    sent = []
    monkeypatch.setattr(mod, "send_admin_text", lambda msg: sent.append(msg))

    try:
        raise TypeError("boom")
    except TypeError as exc:
        mod.maybe_alert_programming_error("scraper_olx", exc)

    assert len(sent) == 1
    assert "TypeError" in sent[0]
    assert "scraper_olx" in sent[0]


def test_does_not_alert_for_non_bug_exception_type(monkeypatch):
    _reset_throttle()
    monkeypatch.setattr(mod.settings, "admin_programming_errors_enabled", True)
    sent = []
    monkeypatch.setattr(mod, "send_admin_text", lambda msg: sent.append(msg))

    try:
        raise ValueError("network timeout")
    except ValueError as exc:
        mod.maybe_alert_programming_error("scraper_olx", exc)

    assert sent == []


def test_does_not_alert_when_disabled_globally(monkeypatch):
    _reset_throttle()
    monkeypatch.setattr(mod.settings, "admin_programming_errors_enabled", False)
    sent = []
    monkeypatch.setattr(mod, "send_admin_text", lambda msg: sent.append(msg))

    try:
        raise NameError("x is not defined")
    except NameError as exc:
        mod.maybe_alert_programming_error("scraper_olx", exc)

    assert sent == []


def test_throttles_repeated_identical_errors(monkeypatch):
    _reset_throttle()
    monkeypatch.setattr(mod.settings, "admin_programming_errors_enabled", True)
    monkeypatch.setattr(mod.settings, "admin_programming_errors_throttle_seconds", 600)
    sent = []
    monkeypatch.setattr(mod, "send_admin_text", lambda msg: sent.append(msg))

    for _ in range(3):
        try:
            raise NameError("x is not defined")
        except NameError as exc:
            mod.maybe_alert_programming_error("scraper_olx", exc)

    assert len(sent) == 1


def test_does_not_throttle_different_components(monkeypatch):
    _reset_throttle()
    monkeypatch.setattr(mod.settings, "admin_programming_errors_enabled", True)
    sent = []
    monkeypatch.setattr(mod, "send_admin_text", lambda msg: sent.append(msg))

    try:
        raise NameError("x is not defined")
    except NameError as exc:
        mod.maybe_alert_programming_error("scraper_olx", exc)
    try:
        raise NameError("x is not defined")
    except NameError as exc:
        mod.maybe_alert_programming_error("scraper_webmotors", exc)

    assert len(sent) == 2
