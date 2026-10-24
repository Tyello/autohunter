from app.bot import handlers_core


def test_normalize_create_feedback_drops_redundant_service_line():
    assert handlers_core._normalize_create_feedback("Wishlist criada com sucesso.") == ""


def test_normalize_create_feedback_keeps_other_service_messages():
    msg = "Wishlist criada com sucesso.\nOutra linha."
    assert handlers_core._normalize_create_feedback(msg) == "Outra linha."
