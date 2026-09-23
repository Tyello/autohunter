"""Regressão: source_configs.force_browser=True (ctx.force_browser) deve forçar o
caminho via Playwright no OLX, sem depender apenas de settings.olx_force_browser
(env) ou do force-browser runtime interno acionado só depois de bloqueios."""

from unittest.mock import patch

from app.scrapers import olx as olx_mod
from app.services.browser_fetcher import BrowserJsonFetchResult
from app.sources.types import ScrapeContext


def test_scrape_olx_respects_ctx_force_browser_even_when_env_flag_is_off():
    ctx = ScrapeContext(source="olx", force_browser=True)

    fake_next_data = {
        "listId": "123456",
        "friendlyUrl": "https://www.olx.com.br/item/carro-123456",
        "subject": "Carro Teste",
    }

    with (
        patch.object(olx_mod.settings, "olx_force_browser", False),
        patch.object(olx_mod.settings, "enable_playwright", True),
        patch.object(
            olx_mod,
            "fetch_json_browser",
            return_value=BrowserJsonFetchResult(
                data=fake_next_data, final_url="https://www.olx.com.br/x", data_url="https://www.olx.com.br/x"
            ),
        ) as mock_browser,
        patch.object(
            olx_mod, "_fetch_http_hybrid", side_effect=AssertionError("HTTP path should not run when force_browser is set")
        ),
    ):
        result = olx_mod.scrape_olx("https://www.olx.com.br/some-search", ctx)

    mock_browser.assert_called_once()
    assert len(result) == 1
    assert result[0]["external_id"] == "123456"
