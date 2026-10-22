"""Anti-bot detector (vendored from Crawl4AI) + integration in the fetch layer.

Tier 3 (structural) is OFF for blocking decisions because it false-positives on
trimmed/RSC-shell fixtures; those cases are pinned below as documentation.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.scrapers import fetching
from app.scrapers.base import FetchBlocked, classify_block
from app.scrapers.shared.antibot_detector import is_blocked, local_block_reason, shadow_reason

FIX = Path(__file__).parent / "fixtures"
SR = FIX / "source_regression"

REALISTIC_FIXTURES = [
    FIX / "gogarage/search_cards.html",
    FIX / "olx/search_cards_fallback.html",
    SR / "chavesnamao/2026-09-28_civic/listing.html",
    SR / "gogarage/2026-09-28_civic/listing.html",
    SR / "kavak/2026-09-28_civic/listing.html",
    SR / "mobiauto/2026-09-28_civic/listing.html",
    SR / "olx/2026-09-28_civic/listing.html",
    SR / "turboclass/2026-09-28_civic/listing.html",
    SR / "mercadolivre/basic_realistic/listing.html",
]

# The 9 legit (trimmed/shell) fixtures Tier 3 would wrongly flag: the reason it is disabled.
TIER3_FALSE_POSITIVES = [
    FIX / "olx/audi_a4_avant_2019_detail.html",
    FIX / "olx/honda_civic_coupe_2015_detail.html",
    FIX / "olx/honda_civic_coupe_2015_detail_share_placeholder.html",
    FIX / "olx/honda_civic_hatch_1993_detail.html",
    FIX / "olx/search_rsc_price_nodes.html",
    SR / "icarros/basic_realistic/detail_52934717.html",
    SR / "icarros/basic_realistic/detail_52934718.html",
    SR / "icarros/basic_realistic/listing.html",
    SR / "mercadolivre/basic_realistic/detail_MLB6177621992.html",
]

LEGIT_FIXTURES = REALISTIC_FIXTURES + TIER3_FALSE_POSITIVES


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


@pytest.mark.parametrize("path", LEGIT_FIXTURES, ids=_id)
def test_legit_fixtures_not_blocked(path):
    html = _read(path)
    assert is_blocked(200, html, structural=False) == (False, "")
    assert classify_block(200, html) == ""


@pytest.mark.parametrize("path", TIER3_FALSE_POSITIVES, ids=_id)
def test_tier3_false_positives_documented(path):
    """structural=True flags these legit pages -> why Tier 3 is shadow-only."""
    assert len(TIER3_FALSE_POSITIVES) == 9
    html = _read(path)
    blocked, reason = is_blocked(200, html, structural=True)
    assert blocked and reason.startswith("Structural")
    assert shadow_reason(200, html).startswith("Structural")


def test_olx_rsc_shell_is_the_main_tier3_case():
    html = _read(FIX / "olx/search_rsc_price_nodes.html")
    assert is_blocked(200, html, structural=False) == (False, "")
    assert is_blocked(200, html, structural=True)[0] is True


def test_known_gap_ml_real_block_not_detected_by_tier1_tier2():
    """Known gap: real ML block page is not caught by Tier 1/2 (ML out of scope)."""
    html = _read(SR / "mercadolivre/2026-09-28_civic/listing_shell_com_cookies_bloqueado.html")
    assert is_blocked(200, html, structural=False, local=False) == (False, "")


POSITIVES = {
    "cloudflare_form": '<html><body><form id="challenge-form" action="/x?__cf_chl_f_tk=abc"></form></body></html>',
    "cloudflare_js": '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1"></script>',
    "perimeterx": "<html><script>window._pxAppId = 'PX123';</script><body>Press and hold</body></html>",
    "datadome": '<iframe src="https://geo.captcha-delivery.com/captcha/?x=1"></iframe>',
    "akamai": "<html><body><h1>Pardon Our Interruption</h1></body></html>",
    "incapsula": "<html><body>_Incapsula_Resource</body></html>",
}


@pytest.mark.parametrize("name", sorted(POSITIVES))
def test_positive_samples_blocked(name):
    blocked, reason = is_blocked(200, POSITIVES[name], structural=False)
    assert blocked, reason
    assert classify_block(200, POSITIVES[name])


def test_status_429_and_403_html_blocked():
    assert is_blocked(429, "x" * 500)[0]
    assert is_blocked(403, "<html><body>" + "x" * 300 + "</body></html>")[0]


def test_empty_spa_shell_blocked_only_in_structural_mode():
    shell = "<html><head><script src='a.js'></script></head><body><div id='root'></div></body></html>"
    assert is_blocked(200, shell, structural=False) == (False, "")
    assert is_blocked(200, shell, structural=True)[0] is True
    assert shadow_reason(200, shell)


def test_json_never_flagged_even_in_structural_mode():
    assert is_blocked(200, '{"items": []}', structural=True) == (False, "")
    assert classify_block(200, '{"items": []}', "application/json") == ""


def test_classify_block_skips_crawl4ai_patterns_for_non_html():
    assert classify_block(200, POSITIVES["akamai"], "application/json") == ""
    assert classify_block(200, POSITIVES["akamai"], "text/html; charset=utf-8").startswith("antibot:")


@pytest.mark.parametrize(
    "html",
    [
        "<html>cloudflare just a moment</html>",
        "<html>cloudflare cf-chl</html>",
        "<html>incapsula</html>",
        "<html>datadome captcha</html>",
        "<html>perimeterx px-captcha</html>",
        "<html>hcaptcha</html>",
        "<html>recaptcha data-sitekey=1</html>",
        "<html>Access Denied</html>",
        "<html>Are you human?</html>",
    ],
)
def test_legacy_keyword_detections_preserved(html):
    assert local_block_reason(html)
    assert classify_block(200, html) == "bot_challenge"


def test_bare_cloudflare_word_is_not_a_block():
    assert classify_block(200, "<html><body><p>cloudflareinsights beacon</p></body></html>") == ""


# --- fetching.py / base.py integration ---------------------------------------

def _ctx():
    return SimpleNamespace(source="olx", force_browser=False)


def test_antibot_reason_triggers_browser_warmup(monkeypatch):
    monkeypatch.setattr(fetching.settings, "enable_playwright", True, raising=False)
    calls = {"http": 0}
    good = "<html><body>" + "<p>ok</p>" * 20 + "</body></html>"

    def fake_http(url, **kw):
        calls["http"] += 1
        if calls["http"] == 1:
            raise FetchBlocked(200, url, reason="antibot:Akamai challenge (Pardon Our Interruption)")
        return good

    monkeypatch.setattr(fetching, "fetch_html", fake_http)
    browser = SimpleNamespace(html=good)
    ctx = _ctx()
    with patch.object(fetching, "fetch_html_browser", return_value=browser) as fb:
        out = fetching.fetch_html_with_browser_fallback("https://x/y", ctx=ctx)
    assert fb.called and calls["http"] == 2
    assert out == good
    assert ctx._hybrid_block_reason.startswith("antibot:")


def test_challenge_never_reaches_parser_after_browser_fallback(monkeypatch):
    monkeypatch.setattr(fetching.settings, "enable_playwright", True, raising=False)

    def fake_http(url, **kw):
        raise FetchBlocked(200, url, reason="antibot:PerimeterX block")

    monkeypatch.setattr(fetching, "fetch_html", fake_http)
    browser = SimpleNamespace(html=POSITIVES["akamai"])
    ctx = _ctx()
    with patch.object(fetching, "fetch_html_browser", return_value=browser):
        with pytest.raises(FetchBlocked) as exc:
            fetching.fetch_html_with_browser_fallback("https://x/y", ctx=ctx)
    assert exc.value.reason == "blocked_after_browser_fallback"
    assert ctx._hybrid_block_reason.startswith("antibot:")


def _fake_session(monkeypatch, text):
    from app.scrapers import base

    class Resp:
        status_code = 200
        headers = {"Content-Type": "text/html"}

        def __init__(self):
            self.text = text

        def raise_for_status(self):
            pass

    class Sess:
        def get(self, *a, **k):
            return Resp()

    monkeypatch.setattr(base, "_get_session", lambda *a, **k: Sess())
    monkeypatch.setattr(base, "_ensure_session_fingerprint", lambda s: None)
    monkeypatch.setattr(base, "_apply_hybrid_cookies", lambda s, c: None)
    return base


def test_base_fetch_200_challenge_raises_antibot(monkeypatch):
    base = _fake_session(monkeypatch, POSITIVES["akamai"])
    with pytest.raises(FetchBlocked) as exc:
        base.fetch_html("https://x/y", min_delay_ms=0, max_delay_ms=0)
    assert exc.value.reason.startswith("antibot:")


def test_shadow_tier3_recorded_but_not_blocking(monkeypatch):
    shell = _read(FIX / "olx/search_rsc_price_nodes.html")
    base = _fake_session(monkeypatch, shell)
    ctx = SimpleNamespace(source="olx")
    assert base.fetch_html("https://x/y", ctx=ctx, min_delay_ms=0, max_delay_ms=0) == shell
    assert ctx.antibot_shadow_tier3.startswith("Structural")


# --- Cloudflare "Attention Required!" (captured from a real OLX block, anonymized) ---

CF_ATTENTION = FIX / "antibot" / "cloudflare_attention_required.html"


def test_cloudflare_attention_required_page_is_blocked():
    """Real block page served with HTTP 200 by Cloudflare; Tier 1/2 of Crawl4AI miss it
    and the old base.py heuristic missed it too (only olx.py's own check caught it)."""
    html = _read(CF_ATTENTION)
    assert is_blocked(200, html, structural=False, local=False) == (False, "")  # upstream gap
    assert local_block_reason(html)
    assert classify_block(200, html, "text/html") == "bot_challenge"
    assert is_blocked(200, html, structural=False)[0] is True


def test_attention_required_phrase_alone_is_not_a_block():
    page = "<html><head><title>Minha conta</title></head><body><p>Attention required: confirme seu e-mail.</p></body></html>"
    assert classify_block(200, page, "text/html") == ""
