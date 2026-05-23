from datetime import datetime, timezone

from app.bot.admin_helpers import (
    as_utc,
    fmt_dt,
    parse_admin_bool,
    render_rejection_reason_label,
    sample_to_match_like,
    short,
)


def test_sample_to_match_like_parses_location_fallback():
    match_like = sample_to_match_like({"title": "Carro", "location": "São Paulo / SP", "ends_at": "2026-01-01"})
    assert match_like.title == "Carro"
    assert match_like.auction_end_at == "2026-01-01"
    assert match_like.city == "São Paulo"
    assert match_like.state == "SP"


def test_render_rejection_reason_label_and_unknown():
    assert render_rejection_reason_label("score_below_min") == "score abaixo do mínimo"
    assert render_rejection_reason_label("custom_reason") == "custom_reason"


def test_fmt_dt_and_as_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert as_utc(None) is None
    assert as_utc(naive).tzinfo == timezone.utc
    assert fmt_dt(aware) == "2026-01-01 12:00:00Z"


def test_parse_admin_bool():
    assert parse_admin_bool("sim") is True
    assert parse_admin_bool("NÃO") is False
    assert parse_admin_bool("talvez") is None


def test_short_compacts_and_truncates():
    assert short("   ") == "-"
    assert short("a   b   c") == "a b c"
    assert short("abcdef", 5) == "ab..."
