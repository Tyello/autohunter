from app.integrations.facebook.constants import STATUS_DISABLED, STATUS_PENDING_AUTH
from app.integrations.facebook.service import issue_pairing_code
from app.models.fb_session import FBSession


def test_router_start_complete_dry_run(client, db, monkeypatch):
    sess = issue_pairing_code(db, "u-router")
    sess_complete = issue_pairing_code(db, "u-router-complete")

    async def _fake_start(user_id: str, profile_dir: str, correlation_id: str):
        return None

    async def _fake_complete(db_, code: str):
        return sess

    import app.web.routes_auth_facebook as routes

    monkeypatch.setattr(routes, "start_onboarding", _fake_start)
    monkeypatch.setattr(routes, "complete_onboarding", _fake_complete)

    res_start = client.post("/auth/facebook/start", json={"code": sess.pairing_code.lower()})
    assert res_start.status_code == 200
    assert res_start.json()["ok"] is True

    res_complete = client.post("/auth/facebook/complete", json={"code": sess_complete.pairing_code})
    assert res_complete.status_code == 200
    assert res_complete.json()["status"] == STATUS_PENDING_AUTH


def test_router_rate_limited_returns_429(client, db, monkeypatch):
    sess = issue_pairing_code(db, "u-rate")

    import app.web.routes_auth_facebook as routes

    async def _always_limited(request, code, endpoint):
        from fastapi import HTTPException

        raise HTTPException(status_code=429, detail={"error": "rate_limited", "reason": "forced"})

    monkeypatch.setattr(routes, "_apply_rate_limit", _always_limited)

    res = client.post("/auth/facebook/start", json={"code": sess.pairing_code})
    assert res.status_code == 429
    assert res.json()["detail"]["error"] == "rate_limited"


def test_router_disabled_rejected(client, db):
    sess = issue_pairing_code(db, "u-disabled")
    row = db.query(FBSession).filter_by(user_id="u-disabled").one()
    row.status = STATUS_DISABLED
    db.commit()

    res = client.post("/auth/facebook/start", json={"code": sess.pairing_code})
    assert res.status_code == 400
    assert res.json()["detail"] == "disabled"
