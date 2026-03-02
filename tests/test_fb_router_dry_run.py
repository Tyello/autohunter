from app.integrations.facebook.constants import STATUS_PENDING_AUTH
from app.integrations.facebook.service import issue_pairing_code


def test_router_start_complete_dry_run(client, db, monkeypatch):
    sess = issue_pairing_code(db, "u-router")

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

    res_complete = client.post("/auth/facebook/complete", json={"code": sess.pairing_code})
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
