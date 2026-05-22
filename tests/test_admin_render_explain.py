from app.bot.handlers_admin import _render_run_summary_lines, _render_webmotors_blocked_diag_lines


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


def test_admin_render_includes_webmotors_diag_note():
    summary = {
        "status": "ERR",
        "found": 0,
        "inserted": 0,
        "matched": 0,
        "queued": 0,
        "reason_buckets": {"proxy_error": 1},
        "last_error": {"category": "webmotors_proxy", "http_status": None, "retryable": True},
        "notes": ["wm_diag bucket=PROXY stage=browser_fetch path=browser_proxy attempts=1"],
    }
    lines = _render_run_summary_lines(summary)
    assert any("wm_diag bucket=PROXY" in l for l in lines)


def test_admin_render_blocked_wm_diag_structured():
    payload = {
        "webmotors_diag": {
            "bucket": "BLOCKED",
            "fetch_path": "browser_direct",
            "attempt": 1,
            "blocked_reason": "bot_challenge_fingerprint",
            "page_title": "Access to this page has been denied",
            "detected_signals": [
                "provider=perimeterx",
                "snippet=Pressione e segure para confirmar que você é um humano",
            ],
        }
    }
    lines = _render_webmotors_blocked_diag_lines(payload)
    text = "\n".join(lines)
    assert "provider=perimeterx" in text
    assert "Access to this page has been denied" in text
    assert "bloqueio anti-bot/fingerprint" in text


def test_admin_render_blocked_without_wm_diag_keeps_empty():
    assert _render_webmotors_blocked_diag_lines({"run_summary": {"notes": ["x"]}}) == []
