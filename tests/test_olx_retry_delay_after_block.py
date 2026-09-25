"""Regressao: apos um bloqueio HTTP inicial (403/challenge), o retry pos-warmup do
browser usava um delay bem mais curto (400-1200ms) que a primeira tentativa
(1200-4200ms). Retentar rapido logo depois de um bloqueio parece mais bot, nao
menos, e arrisca aprofundar o flag de anti-bot em vez de se recuperar dele --
o retry deve usar o mesmo delay (ou maior) que a tentativa inicial."""

from unittest.mock import patch

from app.scrapers import olx as olx_mod
from app.scrapers.base import FetchBlocked
from app.sources.types import ScrapeContext


def test_scrape_olx_retry_after_block_uses_same_delay_as_first_attempt():
    ctx = ScrapeContext(source="olx")

    calls: list[dict] = []

    def _fake_fetch_http_hybrid(search_url, ctx, *, min_delay_ms, max_delay_ms):
        calls.append({"min_delay_ms": min_delay_ms, "max_delay_ms": max_delay_ms})
        if len(calls) == 1:
            raise FetchBlocked(403, search_url, reason="http_status")
        return "<html><a data-testid=\"adcard-link\" href=\"/item-123456\">Carro Teste</a></html>"

    with (
        patch.object(olx_mod.settings, "olx_force_browser", False),
        patch.object(olx_mod.settings, "enable_playwright", True),
        patch.object(olx_mod.settings, "enable_olx_browser_fallback", True),
        patch.object(olx_mod, "_fetch_http_hybrid", side_effect=_fake_fetch_http_hybrid),
        patch.object(olx_mod, "fetch_html_browser", return_value=type("R", (), {"html": "<html></html>"})()),
    ):
        olx_mod.scrape_olx("https://www.olx.com.br/some-search", ctx)

    assert len(calls) == 2, "expected one blocked attempt followed by one retry"
    first_attempt, retry = calls
    assert retry["min_delay_ms"] >= first_attempt["min_delay_ms"]
    assert retry["max_delay_ms"] >= first_attempt["max_delay_ms"]
