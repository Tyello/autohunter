from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.scrapers import olx as olx_module
from app.scrapers.olx import (
    _enrich_missing_olx_thumbnails,
    _extract_olx_detail_thumbnail,
    _looks_like_cf_or_bot,
    OlxItem,
)
from app.sources.types import ScrapeContext


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeCfRequests:
    """Fake cf_requests module that records calls and returns controlled responses."""

    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, "kwargs": kwargs})
        return self.response


def test_real_fixture_honda_civic_2015_extracts_thumbnail():
    """Load real HTML fixture and extract thumbnail correctly for Honda Civic 2015."""
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "honda_civic_coupe_2015_detail.html"
    html = fixture_path.read_text(encoding="utf-8")
    url = (
        "https://sp.olx.com.br/regiao-de-ribeirao-preto/autos-e-pecas/"
        "carros-vans-e-utilitarios/honda-civic-coupe-si-2-4-16v-206cv-mec-2p-2015-1525422289"
    )
    thumb = _extract_olx_detail_thumbnail(html, url)
    assert thumb == "https://img.olx.com.br/images/43/433605438030577.jpg"


def test_real_fixture_audi_a4_2019_extracts_thumbnail():
    """Load real HTML fixture and extract thumbnail correctly for Audi A4 2019."""
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "audi_a4_avant_2019_detail.html"
    html = fixture_path.read_text(encoding="utf-8")
    url = (
        "https://rj.olx.com.br/norte-do-estado-do-rio/autos-e-pecas/"
        "carros-vans-e-utilitarios/audi-a4-avant-prest-plus-2-0-tfsi-s-tronic-2019-1524357204"
    )
    thumb = _extract_olx_detail_thumbnail(html, url)
    assert thumb == "https://img.olx.com.br/images/48/488699432043826.jpg"


def test_enrich_uses_hardened_fetch_when_cf_requests_available(monkeypatch):
    """Verify that _enrich_missing_olx_thumbnails uses hardened cf_requests fetch when available."""
    # Load Honda fixture HTML
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "honda_civic_coupe_2015_detail.html"
    honda_html = fixture_path.read_text(encoding="utf-8")

    # Create fake cf_requests that returns our Honda fixture
    fake_response = _FakeResponse(status_code=200, text=honda_html)
    fake_cf = _FakeCfRequests(response=fake_response)

    # Monkeypatch cf_requests module
    monkeypatch.setattr(olx_module, "cf_requests", fake_cf)

    # Create item without thumbnail
    item = OlxItem(
        external_id="1",
        title="Honda",
        url="https://sp.olx.com.br/regiao-de-ribeirao-preto/autos-e-pecas/carros-vans-e-utilitarios/honda-civic-coupe-si-2-4-16v-206cv-mec-2p-2015-1525422289",
        thumbnail_url=None,
        price=None,
    )

    # Call enrichment function
    _enrich_missing_olx_thumbnails([item], ScrapeContext(source="olx"), limit=1)

    # Assert that cf_requests.get was called once
    assert len(fake_cf.calls) == 1

    # Assert that the call included 'impersonate' parameter
    call_kwargs = fake_cf.calls[0]["kwargs"]
    assert "impersonate" in call_kwargs

    # Assert that thumbnail was extracted correctly
    assert item.thumbnail_url == "https://img.olx.com.br/images/43/433605438030577.jpg"


def test_enrich_falls_back_to_fetch_html_when_cf_requests_none(monkeypatch):
    """Verify that _enrich_missing_olx_thumbnails falls back to fetch_html when cf_requests is None."""
    # Load Honda fixture HTML
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "honda_civic_coupe_2015_detail.html"
    honda_html = fixture_path.read_text(encoding="utf-8")

    # Monkeypatch cf_requests to None (simulating absence)
    monkeypatch.setattr(olx_module, "cf_requests", None)

    # Monkeypatch fetch_html to return Honda fixture
    monkeypatch.setattr(olx_module, "fetch_html", lambda *_a, **_k: honda_html)

    # Create item without thumbnail
    item = OlxItem(
        external_id="1",
        title="Honda",
        url="https://sp.olx.com.br/regiao-de-ribeirao-preto/autos-e-pecas/carros-vans-e-utilitarios/honda-civic-coupe-si-2-4-16v-206cv-mec-2p-2015-1525422289",
        thumbnail_url=None,
        price=None,
    )

    # Call enrichment function
    _enrich_missing_olx_thumbnails([item], ScrapeContext(source="olx"), limit=1)

    # Assert that thumbnail was extracted correctly (fallback path worked)
    assert item.thumbnail_url == "https://img.olx.com.br/images/43/433605438030577.jpg"


def test_enrich_logs_blocked_distinctly_from_no_image(monkeypatch, caplog):
    """Verify that FetchBlocked (403) is logged distinctly from 'no image found' case."""
    # Create fake cf_requests that simulates a 403 Forbidden response
    fake_response = _FakeResponse(status_code=403, text="")
    fake_cf = _FakeCfRequests(response=fake_response)

    # Monkeypatch cf_requests to our fake
    monkeypatch.setattr(olx_module, "cf_requests", fake_cf)

    # Create item without thumbnail
    item = OlxItem(
        external_id="1",
        title="Item",
        url="https://sp.olx.com.br/item/123",
        thumbnail_url=None,
        price=None,
    )

    # Call enrichment with caplog at WARNING level
    with caplog.at_level(logging.WARNING, logger=olx_module.__name__):
        _enrich_missing_olx_thumbnails([item], ScrapeContext(source="olx"), limit=1)

    # Assert that a log record with "blocked" (case-insensitive) exists
    assert any("blocked" in r.message.lower() for r in caplog.records), \
        f"Expected 'blocked' in logs, got: {[r.message for r in caplog.records]}"

    # Assert that no log record contains "no thumbnail found on detail page" for this item
    # (because the error was BLOCKED, not missing image)
    assert not any(
        "no thumbnail found on detail page" in r.message
        for r in caplog.records
    ), \
        f"Should not log 'no thumbnail found' when blocked, got: {[r.message for r in caplog.records]}"


def test_normal_olx_page_with_cloudflare_beacon_is_not_flagged_as_blocked():
    """Regression: OLX embeds Cloudflare's insights/bot-management beacon
    script on ordinary, fully-rendered pages -- confirmed by fetching the
    live detail page for the listing reported in the third "photo missing"
    bug report (honda-civic-hatch-lsi-1993-1528830068). A bare substring
    match on "cloudflare" flagged this normal 200 response as a bot
    challenge, so `_fetch_olx_detail_html` raised FetchBlocked before
    `_extract_olx_detail_thumbnail` ever ran, discarding a perfectly good
    thumbnail.
    """
    fixture_path = Path(__file__).parent / "fixtures" / "olx" / "honda_civic_hatch_1993_detail.html"
    html = fixture_path.read_text(encoding="utf-8")

    assert not _looks_like_cf_or_bot(html), (
        "A page containing OLX's normal cloudflareinsights.com beacon script "
        "must not be treated as a bot-challenge interstitial"
    )

    url = (
        "https://sp.olx.com.br/sao-paulo-e-regiao/autos-e-pecas/"
        "carros-vans-e-utilitarios/honda-civic-hatch-lsi-1993-1528830068"
    )
    assert _extract_olx_detail_thumbnail(html, url) == "https://img.olx.com.br/images/45/457640190569927.jpg"


def test_actual_bot_challenge_page_is_still_flagged_as_blocked():
    """Sanity check for the narrowed heuristic: a real Cloudflare interstitial
    (distinguishable by its "Just a moment..." / "Checking your browser"
    copy) must still be detected as blocked."""
    challenge_html = (
        "<html><head><title>Just a moment...</title></head>"
        "<body>Checking your browser before accessing olx.com.br. "
        "This process is automatic. cloudflare ray id.</body></html>"
    )
    assert _looks_like_cf_or_bot(challenge_html)


def test_olx_share_placeholder_og_image_is_rejected_in_favor_of_real_photo():
    """Regression: OLX's own og:image meta tag can point at its generic
    sharing placeholder (static.olx.com.br/cd/vi/images/olx-share.jpg)
    instead of a real listing photo, while the real photos remain available
    in the page's JSON-LD product data -- confirmed live for
    honda-civic-coupe-si-2-4-16v-206cv-mec-2p-2015-1525422289.
    `_extract_olx_detail_thumbnail` used to trust og:image unconditionally
    and would notify users with OLX's generic share image instead of the
    car's actual photo.
    """
    fixture_path = (
        Path(__file__).parent / "fixtures" / "olx" / "honda_civic_coupe_2015_detail_share_placeholder.html"
    )
    html = fixture_path.read_text(encoding="utf-8")

    url = "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios/honda-civic-coupe-si-2-4-16v-206cv-mec-2p-2015-1525422289"
    thumb = _extract_olx_detail_thumbnail(html, url)

    assert thumb == "https://img.olx.com.br/images/25/251678911875003.jpg"
    assert thumb is not None and "olx-share" not in thumb
