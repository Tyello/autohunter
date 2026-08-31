from app.integrations.facebook.service import generate_pairing_code


def test_pairing_code_format():
    code = generate_pairing_code()
    assert code.startswith("FB-")
    assert len(code) == 7
