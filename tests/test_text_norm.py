from __future__ import annotations

from app.core.text_norm import normalize, tokens


def test_normalize_removes_accents_and_punctuation():
    assert normalize("São Paulo, SP") == "sao paulo sp"


def test_tokens_split_and_lowercase():
    assert tokens("Civic SI 1994!") == ["civic", "si", "1994"]
