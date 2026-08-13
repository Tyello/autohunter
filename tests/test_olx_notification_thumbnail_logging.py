from __future__ import annotations

import logging

import pytest

from app.bot import media as media_module
from app.bot import sender as sender_module
from app.scrapers import olx as olx_module
from app.scrapers.olx import _enrich_missing_olx_thumbnails, _extract_olx_detail_thumbnail, OlxItem
from app.sources.types import ScrapeContext


# Real HTML fixture: <meta property="og:image"> as served by the OLX detail
# page for https://rj.olx.com.br/.../audi-a4-avant-prest-plus-2-0-tfsi-s-tronic-2019-1524357204
# (the listing reported as arriving without a photo in the Telegram alert).
OLX_AUDI_A4_DETAIL_HTML = """
<html><head>
<meta property="og:image" content="https://img.olx.com.br/images/48/488699432043826.jpg">
</head><body></body></html>
"""


class _LenientListing:
    """Minimal stand-in for a car_listings row: unset attrs resolve to None."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __getattr__(self, name):
        return None


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return {"ok": True, "result": {"message_id": 1}}


class _FakeSession:
    """Records every POST so we can assert whether sendPhoto/sendMessage fired."""

    def __init__(self, photo_response: _FakeResponse):
        self.photo_response = photo_response
        self.calls: list[str] = []

    def post(self, url, **kwargs):
        if url.endswith("/sendPhoto"):
            self.calls.append("sendPhoto")
            return self.photo_response
        self.calls.append("sendMessage")
        return _FakeResponse(200)


def test_olx_detail_page_thumbnail_extracts_correctly_for_reported_listing():
    """The exact listing from the bug report DOES have an extractable photo."""
    url = (
        "https://rj.olx.com.br/norte-do-estado-do-rio/autos-e-pecas/"
        "carros-vans-e-utilitarios/audi-a4-avant-prest-plus-2-0-tfsi-s-tronic-2019-1524357204"
    )
    thumb = _extract_olx_detail_thumbnail(OLX_AUDI_A4_DETAIL_HTML, url)
    assert thumb == "https://img.olx.com.br/images/48/488699432043826.jpg"


def test_telegram_sender_logs_warning_when_thumbnail_url_missing(monkeypatch, caplog):
    """No thumbnail_url at all -> falls back to sendMessage, and must log why."""
    monkeypatch.setattr(sender_module.settings, "telegram_bot_token", "TEST_TOKEN")
    fake_session = _FakeSession(photo_response=_FakeResponse(200))
    monkeypatch.setattr(sender_module, "get_shared_session", lambda *_a, **_k: fake_session)

    listing = _LenientListing(
        title="Audi A4 Avant", url="https://olx.com.br/item/x", thumbnail_url=None, source="olx",
    )
    notification = _LenientListing(reason=None)
    user = _LenientListing(telegram_chat_id=123)

    with caplog.at_level(logging.WARNING, logger=sender_module.__name__):
        sender_module.telegram_sender(notification, listing, user)

    assert fake_session.calls == ["sendMessage"]
    assert any("no thumbnail_url" in r.message and "sending text-only alert" in r.message for r in caplog.records)


def test_telegram_sender_logs_warning_when_thumbnail_download_fails(monkeypatch, caplog):
    """thumbnail_url present but download fails -> silent fallback must now log."""
    monkeypatch.setattr(sender_module.settings, "telegram_bot_token", "TEST_TOKEN")
    fake_session = _FakeSession(photo_response=_FakeResponse(200))
    monkeypatch.setattr(sender_module, "get_shared_session", lambda *_a, **_k: fake_session)
    monkeypatch.setattr(sender_module, "download_image_bytes", lambda *_a, **_k: None)

    listing = _LenientListing(
        title="Audi A4 Avant",
        url="https://olx.com.br/item/x",
        thumbnail_url="https://img.olx.com.br/images/48/488699432043826.jpg",
        source="olx",
    )
    notification = _LenientListing(reason=None)
    user = _LenientListing(telegram_chat_id=123)

    with caplog.at_level(logging.WARNING, logger=sender_module.__name__):
        sender_module.telegram_sender(notification, listing, user)

    assert fake_session.calls == ["sendMessage"]
    assert any("could not download thumbnail" in r.message for r in caplog.records)


def test_telegram_sender_logs_warning_when_send_photo_api_fails(monkeypatch, caplog):
    """Telegram sendPhoto returns an error -> silent fallback must now log."""
    monkeypatch.setattr(sender_module.settings, "telegram_bot_token", "TEST_TOKEN")
    fake_session = _FakeSession(photo_response=_FakeResponse(400, "wrong type of the web page content"))
    monkeypatch.setattr(sender_module, "get_shared_session", lambda *_a, **_k: fake_session)
    monkeypatch.setattr(sender_module, "download_image_bytes", lambda *_a, **_k: (b"bytes", "image/jpeg"))

    listing = _LenientListing(
        title="Audi A4 Avant",
        url="https://olx.com.br/item/x",
        thumbnail_url="https://img.olx.com.br/images/48/488699432043826.jpg",
        source="olx",
    )
    notification = _LenientListing(reason=None)
    user = _LenientListing(telegram_chat_id=123)

    with caplog.at_level(logging.WARNING, logger=sender_module.__name__):
        sender_module.telegram_sender(notification, listing, user)

    assert fake_session.calls == ["sendPhoto", "sendMessage"]
    assert any("sendPhoto failed" in r.message for r in caplog.records)


def test_download_image_bytes_logs_warning_on_non_200(monkeypatch, caplog):
    class _Resp:
        status_code = 403
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Sess:
        def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(media_module, "get_shared_session", lambda *_a, **_k: _Sess())

    with caplog.at_level(logging.WARNING, logger=media_module.__name__):
        result = media_module.download_image_bytes("https://img.olx.com.br/blocked.jpg")

    assert result is None
    assert any("HTTP 403" in r.message for r in caplog.records)


def test_enrich_missing_olx_thumbnails_warns_when_cap_is_exceeded(monkeypatch, caplog):
    items = [
        OlxItem(external_id=str(i), title=f"item {i}", url=f"https://olx.com.br/item/{i}", thumbnail_url=None, price=None)
        for i in range(5)
    ]
    # Force the fetch_html fallback path (no TLS-impersonation lib available) so this test
    # exercises the same fake HTML it monkeypatches, instead of a real cf_requests network call.
    monkeypatch.setattr(olx_module, "cf_requests", None)
    monkeypatch.setattr(
        olx_module, "fetch_html", lambda *_a, **_k: '<meta property="og:image" content="https://img.olx.com.br/x.jpg">'
    )

    with caplog.at_level(logging.WARNING, logger=olx_module.__name__):
        _enrich_missing_olx_thumbnails(items, ScrapeContext(source="olx"), limit=2)

    assert items[0].thumbnail_url == "https://img.olx.com.br/x.jpg"
    assert items[1].thumbnail_url == "https://img.olx.com.br/x.jpg"
    assert items[2].thumbnail_url is None
    assert any("cap is 2" in r.message for r in caplog.records)


def test_enrich_missing_olx_thumbnails_warns_when_detail_page_has_no_image(monkeypatch, caplog):
    items = [OlxItem(external_id="1", title="item", url="https://olx.com.br/item/1", thumbnail_url=None, price=None)]
    # Force the fetch_html fallback path (no TLS-impersonation lib available) so this test
    # exercises the same fake HTML it monkeypatches, instead of a real cf_requests network call.
    monkeypatch.setattr(olx_module, "cf_requests", None)
    monkeypatch.setattr(olx_module, "fetch_html", lambda *_a, **_k: "<html><body>no image here</body></html>")

    with caplog.at_level(logging.WARNING, logger=olx_module.__name__):
        _enrich_missing_olx_thumbnails(items, ScrapeContext(source="olx"), limit=5)

    assert items[0].thumbnail_url is None
    assert any("no thumbnail found on detail page" in r.message for r in caplog.records)
