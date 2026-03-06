from app.bot.handlers_admin import _render_run_summary_lines


def test_admin_render_includes_queued_zero_explain():
    summary = {
        "status": "OK",
        "found": 40,
        "inserted": 10,
        "matched": 12,
        "queued": 0,
        "reason_buckets": {
            "already_notified": 11,
            "filtered_year": 1,
        },
        "last_error": None,
    }

    lines = _render_run_summary_lines(summary)
    text = "\n".join(lines)

    assert "queued=0 porque:" in text
    assert "already_notified=11" in text
