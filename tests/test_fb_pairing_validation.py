from datetime import timedelta

from app.integrations.facebook.constants import STATUS_ACTIVE, STATUS_DISABLED, STATUS_PENDING_AUTH
from app.integrations.facebook.guards import can_transition_status, normalize_pairing_code, validate_pairing_code_format
from app.integrations.facebook.service import issue_pairing_code, validate_pairing_code
from app.models.fb_session import FBSession


def test_pairing_regex_and_normalization():
    assert normalize_pairing_code(" fb-ab12 ") == "FB-AB12"
    assert validate_pairing_code_format("FB-AB12") is True
    assert validate_pairing_code_format("FB-abc1") is False
    assert validate_pairing_code_format("FB-ABCDE") is False


def test_pairing_ttl_expired(db):
    sess = issue_pairing_code(db, "u1")
    row = db.query(FBSession).filter(FBSession.user_id == "u1").one()
    row.pairing_expires_at = row.pairing_expires_at - timedelta(minutes=11)
    db.commit()

    out, _ = validate_pairing_code(db, sess.pairing_code, consume=False)
    assert out.ok is False
    assert out.reason == "code_expired"


def test_pairing_single_use(db):
    sess = issue_pairing_code(db, "u2")
    out1, _ = validate_pairing_code(db, sess.pairing_code, consume=True)
    out2, _ = validate_pairing_code(db, sess.pairing_code, consume=False)
    assert out1.ok is True
    assert out2.ok is False
    assert out2.reason == "code_already_used"


def test_pairing_disabled_rejected(db):
    sess = issue_pairing_code(db, "u3")
    row = db.query(FBSession).filter(FBSession.user_id == "u3").one()
    row.status = STATUS_DISABLED
    db.commit()

    out, _ = validate_pairing_code(db, sess.pairing_code, consume=False)
    assert out.ok is False
    assert out.reason == "disabled"


def test_invalid_status_transitions_are_rejected():
    assert can_transition_status(STATUS_PENDING_AUTH, STATUS_ACTIVE) is True
    assert can_transition_status(STATUS_ACTIVE, STATUS_PENDING_AUTH) is False
    assert can_transition_status(STATUS_DISABLED, STATUS_ACTIVE) is False
