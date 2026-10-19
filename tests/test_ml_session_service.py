"""Rastreio da sessao logada do ML: classificacao, transicoes e resumo sem expor cookies."""

import app.scrapers.hybrid_cookies as hc
from app.services import ml_session_service as svc

NOW = 1_800_000_000.0
ISO = "2027-01-15T08:00:00+00:00"


def test_classify_outcome():
    assert svc.classify_outcome(has_session=True, blocked=False) == "ok"
    assert svc.classify_outcome(has_session=True, blocked=True) == "rejected"
    assert svc.classify_outcome(has_session=False, blocked=True) == "no_session"
    assert svc.classify_outcome(has_session=False, blocked=False) is None


def test_rejected_emits_event_only_on_transition():
    s1, e1 = svc.next_state({"last_outcome": "ok", "ok_count": 4}, "rejected", now_iso=ISO, url="u")
    assert e1 == "ml_session_rejected"
    assert (s1["rejected_count"], s1["ok_count"], s1["last_rejected_url"]) == (1, 4, "u")
    s2, e2 = svc.next_state(s1, "rejected", now_iso=ISO, url="u")
    assert e2 is None and s2["rejected_count"] == 2


def test_recovered_event_after_rejected():
    s, e = svc.next_state({"last_outcome": "rejected"}, "ok", now_iso=ISO)
    assert e == "ml_session_recovered"
    assert s["last_ok_at"] == ISO and s["ok_count"] == 1
    _, e_ok = svc.next_state(s, "ok", now_iso=ISO)
    assert e_ok is None


def _cookies(monkeypatch, cookies):
    monkeypatch.setattr(hc, "_load_storage_state_cookies", lambda **k: cookies)


def test_session_info_logged_in_and_expiry(monkeypatch):
    _cookies(monkeypatch, [
        {"name": "orguserid", "value": "1", "domain": ".mercadolivre.com.br", "expires": NOW + 3600},
        {"name": "ssid", "value": "2", "domain": ".mercadolivre.com.br", "expires": NOW + 7200},
        {"name": "other", "value": "3", "domain": ".google.com", "expires": NOW - 1},
    ])
    info = svc.session_info(now=NOW)
    assert info["logged_in"] is True and info["cookie_count"] == 2
    assert info["auth_cookies_expired"] is False
    assert info["auth_cookies_expire_at"].startswith("2027-01-15")
    assert "value" not in str(info)


def test_session_info_anonymous_or_expired(monkeypatch):
    _cookies(monkeypatch, [{"name": "_d2id", "value": "x", "domain": ".mercadolivre.com.br"}])
    assert svc.session_info(now=NOW)["logged_in"] is False
    _cookies(monkeypatch, [
        {"name": "orguserid", "value": "1", "domain": ".mercadolivre.com.br", "expires": NOW - 10},
        {"name": "ssid", "value": "2", "domain": ".mercadolivre.com.br", "expires": NOW - 10},
    ])
    assert svc.session_info(now=NOW)["auth_cookies_expired"] is True
    _cookies(monkeypatch, [])
    assert svc.session_info(now=NOW)["present"] is False


def test_scrape_records_outcome(monkeypatch):
    from app.scrapers import mercadolivre as ml

    seen = []
    monkeypatch.setattr(ml, "_fetch_html_ml", lambda *a, **k: "<html>account-verification</html>")
    monkeypatch.setattr(ml, "_ml_session_cookies", lambda proxy: {"ssid": "x"})
    monkeypatch.setattr(ml.ml_session_service, "record_outcome", lambda o, **k: seen.append(o))
    try:
        ml._fetch_ml_search_with_shell_fallback("https://lista.mercadolivre.com.br/x", None)
    except ml.FetchBlocked:
        pass
    assert seen == ["rejected"]
