from app.notifications.telegram_formatter import format_ad_message


class _Ad:
    title = "Civic"
    price = 100000
    source = "olx"
    url = "https://example.com/1"
    external_id = "E1"
    notification_id = "abc123"
    reason = "new_match"


def test_notification_has_track_button():
    payload = format_ad_message(_Ad())
    labels = [b["text"] for b in payload.inline_keyboard[0]]
    assert "⭐ Rastrear" in labels
    assert "📉 Alerta de queda" not in labels
