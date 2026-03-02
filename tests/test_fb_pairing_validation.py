from datetime import timedelta

from app.integrations.facebook.service import (
    can_transition_status,
    is_valid_pairing_code,
    issue_pairing_code,
    normalize_pairing_code,
    validate_pairing_code,
)
from app.models.fb_session import FBSession


def test_pairing_code_regex_normalization():
    assert normalize_pairing_code(" fb-ab12 ") == "FB-AB12"
    assert is_valid_pairing_code(" fb-ab12 ") is True
    assert is_valid_pairing_code("FB-ABC") is False


def test_pairing_ttl_expired(db):
    sess = issue_pairing_code(db, "u1")
    row = db.query(FBSession).filter(FBSession.user_id == "u1").one()
    row.pairing_expires_at = row.pairing_expires_at - timedelta(minutes=11)
    db.commit()
    check, _ = validate_pairing_code(db, sess.pairing_code, consume=False)
    assert check.ok is False
    assert check.reason == "code_expired"


def test_pairing_single_use(db):
    sess = issue_pairing_code(db, "u2")
    ok, _ = validate_pairing_code(db, sess.pairing_code, consume=True)
    assert ok.ok is True
    denied, _ = validate_pairing_code(db, sess.pairing_code, consume=False)
    assert denied.ok is False
    assert denied.reason == "code_already_used"


def test_invalid_status_transitions_rejected():
    assert can_transition_status("PENDING_AUTH", "ACTIVE") is True
    assert can_transition_status("DISABLED", "ACTIVE") is False
    assert can_transition_status("ACTIVE", "PENDING_AUTH") is False
