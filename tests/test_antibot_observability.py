"""Observabilidade do detector anti-bot: os sinais precisam chegar ao run payload e
ao system_logs. Regressao: ScrapeContext e dataclass(slots=True); atributos fora dos
campos eram descartados em silencio por object.__setattr__ dentro de try/except, entao
`_hybrid_block_reason` e `antibot_shadow_tier3` nunca chegavam a producao. Estes testes
usam o ScrapeContext REAL (SimpleNamespace esconderia o problema)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.scheduler.jobs import _ctx_fetch_diag, scrape_ingest_match
from app.scrapers import fetching
from app.scrapers.base import FetchBlocked, classify_block, record_antibot_shadow
from app.services.source_execution_helpers import antibot_run_diag, build_run_payload, merge_antibot_diag
from app.services.source_url_cursors_service import touch_cursor
from app.sources.types import ScrapeContext

FIX = Path(__file__).parent / "fixtures"
RSC_SHELL = (FIX / "olx/search_rsc_price_nodes.html").read_text(encoding="utf-8")
CHALLENGE = "<html><body><h1>Pardon Our Interruption</h1></body></html>"


def test_shadow_is_stored_on_real_scrape_context():
    ctx = ScrapeContext(source="olx")
    reason = record_antibot_shadow(ctx, RSC_SHELL, status_code=200, url="https://olx/x")
    assert reason.startswith("Structural")
    assert ctx.antibot_shadow_tier3 == reason
    assert ctx.antibot_shadow_url == "https://olx/x"
    assert ctx.antibot_shadow_count == 1
    record_antibot_shadow(ctx, RSC_SHELL, status_code=200, url="https://olx/y")
    assert ctx.antibot_shadow_count == 2


def test_classify_block_accumulates_detector_time_on_real_ctx():
    ctx = ScrapeContext(source="olx")
    assert classify_block(200, "<html><body><p>ok</p></body></html>" * 50, "text/html", ctx=ctx) == ""
    classify_block(200, CHALLENGE, "text/html", ctx=ctx)
    assert ctx.antibot_detector_calls == 2
    assert ctx.antibot_detector_ms > 0


def test_hybrid_block_reason_is_stored_on_real_ctx(monkeypatch):
    monkeypatch.setattr(fetching.settings, "enable_playwright", True, raising=False)
    good = "<html><body>" + "<p>ok</p>" * 20 + "</body></html>"
    calls = {"n": 0}

    def fake_http(url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FetchBlocked(200, url, reason="antibot:PerimeterX block")
        return good

    monkeypatch.setattr(fetching, "fetch_html", fake_http)
    ctx = ScrapeContext(source="kavak")
    with patch.object(fetching, "fetch_html_browser", return_value=SimpleNamespace(html=good)):
        fetching.fetch_html_with_browser_fallback("https://x/y", ctx=ctx)
    assert ctx._hybrid_blocked is True
    assert ctx._hybrid_block_reason == "antibot:PerimeterX block"


def test_ctx_fetch_diag_exposes_antibot_fields():
    ctx = ScrapeContext(source="olx")
    classify_block(200, CHALLENGE, "text/html", ctx=ctx)
    record_antibot_shadow(ctx, RSC_SHELL, status_code=200, url="https://olx/x")
    object.__setattr__(ctx, "_hybrid_block_reason", "antibot:Akamai challenge")
    diag = _ctx_fetch_diag(ctx)
    assert diag["hybrid_block_reason"] == "antibot:Akamai challenge"
    assert diag["antibot_shadow_tier3"].startswith("Structural")
    assert diag["antibot_shadow_count"] == 1
    assert diag["antibot_detector_calls"] == 1
    assert diag["antibot_detector_ms"] > 0


def test_antibot_run_diag_and_merge_and_payload():
    clean = {"antibot_detector_calls": 0, "antibot_detector_ms": 0.0, "antibot_shadow_count": 0}
    assert antibot_run_diag(clean) is None

    r1 = {"hybrid_block_reason": "antibot:A", "antibot_detector_calls": 2, "antibot_detector_ms": 10.0,
          "antibot_shadow_count": 1, "antibot_shadow_tier3": "Structural: x", "antibot_shadow_url": "https://u1"}
    r2 = {"antibot_detector_calls": 3, "antibot_detector_ms": 20.0, "antibot_shadow_count": 0}
    acc: dict = {}
    merge_antibot_diag(acc, r1)
    merge_antibot_diag(acc, r2)
    d = antibot_run_diag(acc)
    assert d["detector_calls"] == 5
    assert d["detector_ms"] == pytest.approx(30.0)
    assert d["detector_ms_avg"] == pytest.approx(6.0)
    assert d["shadow_count"] == 1
    assert d["block_reasons"] == {"antibot:A": 1}
    assert d["shadow_urls"] == ["https://u1"]

    payload = build_run_payload(
        run_summary={}, run_reason="ok", hybrid_browser_used=False, hybrid_blocked=False,
        hybrid_blocked_status=None, antibot=d,
    )
    assert payload["antibot"]["detector_calls"] == 5
    assert "antibot" not in build_run_payload(
        run_summary={}, run_reason="ok", hybrid_browser_used=False, hybrid_blocked=False, hybrid_blocked_status=None
    )


def test_scrape_ingest_match_logs_shadow_event_with_found(db, monkeypatch):
    """Permite cruzar Tier 3 (sombra) com anuncios parseados na mesma resposta."""
    captured: list[tuple] = []
    monkeypatch.setattr("app.scheduler.jobs.log", lambda *a, **kw: captured.append((a, kw)))
    monkeypatch.setattr("app.scheduler.jobs.emit_event", lambda *a, **kw: None)

    url = "https://turboclass.com.br/anuncio-lista.php?q=civic+si"
    ctx = ScrapeContext(source="turboclass", extra={"incremental_enabled": True})
    touch_cursor(db, source="turboclass", url=url, last_external_id="tc-top")
    db.commit()
    listings = [{
        "source": "turboclass", "external_id": "tc-top", "url": "https://turboclass.com.br/a/tc-top",
        "title": "Honda Civic SI 2007", "price": Decimal("165900.00"), "year": 2007,
        "thumbnail_url": "https://turboclass.com.br/img/tc-top.jpg",
    }]

    def scraper(search_url, ctx=None):
        record_antibot_shadow(ctx, RSC_SHELL, status_code=200, url=search_url)
        return listings

    res = scrape_ingest_match(db, "scraper_turboclass", scraper, url, ctx=ctx, wishlist=None)
    assert res["ok"] is True
    assert res["antibot_shadow_count"] == 1
    events = [kw for a, kw in captured if kw.get("event_type") == "antibot_shadow_tier3"]
    assert len(events) == 1
    payload = captured[[kw.get("event_type") for a, kw in captured].index("antibot_shadow_tier3")][0][4]
    assert payload["found"] == 1
    assert payload["url"] == url
    assert payload["reason"].startswith("Structural")
