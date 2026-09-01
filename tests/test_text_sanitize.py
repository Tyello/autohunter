from __future__ import annotations

from app.bot.text_sanitize import sanitize_for_telegram


def test_empty_string_returns_empty():
    assert sanitize_for_telegram("") == ""


def test_none_returns_none():
    assert sanitize_for_telegram(None) is None


def test_normal_text_is_unchanged():
    assert sanitize_for_telegram("Honda Civic Si 2020") == "Honda Civic Si 2020"


def test_removes_isolated_surrogate_characters():
    text = "Civic \ud800 Si"
    result = sanitize_for_telegram(text)
    assert "\ud800" not in result
    assert "Civic" in result and "Si" in result
