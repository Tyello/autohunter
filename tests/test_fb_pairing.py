from datetime import timedelta

from app.integrations.facebook.service import generate_pairing_code, issue_pairing_code, validate_pairing_code
from app.models.fb_session import FBSession


def test_pairing_code_format():
    code = generate_pairing_code()
    assert code.startswith("FB-")
    assert len(code) == 7


def test_pairing_one_time_and_ttl(db):
    sess = issue_pairing_code(db, "123")
    ok, _ = validate_pairing_code(db, sess.pairing_code, consume=False)
    assert ok.ok is True

    ok2, _ = validate_pairing_code(db, sess.pairing_code, consume=True)
    assert ok2.ok is True

    ok3, _ = validate_pairing_code(db, sess.pairing_code, consume=False)
    assert ok3.ok is False
    assert ok3.reason == "code_already_used"

    row = db.query(FBSession).filter(FBSession.user_id == "123").one()
    row.pairing_used_at = None
    row.pairing_expires_at = row.pairing_expires_at - timedelta(minutes=11)
    db.commit()

    ok4, _ = validate_pairing_code(db, sess.pairing_code, consume=False)
    assert ok4.ok is False
    assert ok4.reason == "code_expired"
