from app.integrations.facebook.validator import classify_marketplace_state


def test_validator_active():
    res = classify_marketplace_state(final_url="https://www.facebook.com/marketplace/", html="<html>Marketplace</html>")
    assert res.status == "ACTIVE"


def test_validator_login_wall():
    res = classify_marketplace_state(final_url="https://www.facebook.com/login", html="<html>Log in</html>")
    assert res.status == "EXPIRED"
    assert res.error_kind == "LOGIN_WALL"


def test_validator_checkpoint():
    res = classify_marketplace_state(final_url="https://www.facebook.com/checkpoint", html="checkpoint")
    assert res.status == "CHALLENGE_REQUIRED"


def test_validator_blocked():
    res = classify_marketplace_state(final_url="https://www.facebook.com/marketplace/", html="suspicious activity")
    assert res.status == "BLOCKED"
