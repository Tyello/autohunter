from app.integrations.facebook.service import issue_pairing_code


def test_router_start_complete_dry_run(client, db, monkeypatch):
    sess = issue_pairing_code(db, "200")

    called = {"start": 0, "complete": 0}

    async def _fake_start(user_id, profile_dir, correlation_id):
        called["start"] += 1

    async def _fake_complete(db_session, code):
        called["complete"] += 1
        return sess

    monkeypatch.setattr("app.web.routes_auth_facebook.start_onboarding", _fake_start)
    monkeypatch.setattr("app.web.routes_auth_facebook.complete_onboarding", _fake_complete)

    r1 = client.post("/auth/facebook/start", json={"code": sess.pairing_code})
    assert r1.status_code == 200
    assert r1.json()["ok"] is True

    r2 = client.post("/auth/facebook/complete", json={"code": sess.pairing_code})
    assert r2.status_code == 200
    assert r2.json()["ok"] is True
    assert called == {"start": 1, "complete": 1}
