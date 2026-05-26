from types import SimpleNamespace

from app.services.source_execution_helpers import build_scrape_dispatch
from app.sources.flags import read_source_impl_flags


def _make_dispatch(*, src: str, impl: str = "v1", canary: bool = False, v2_present: bool = True):
    flags = read_source_impl_flags({"impl": impl, "mercadolivre_v2_canary_enabled": canary})
    plugin = SimpleNamespace(scrape=lambda *_args, **_kwargs: [{"external_id": "v1"}])
    v2_scraper = SimpleNamespace(scrape=lambda *_args, **_kwargs: SimpleNamespace(listings=[{"external_id": "v2"}], warnings=[], blocked=False, partial_failure=False)) if v2_present else None
    return build_scrape_dispatch(
        src=src,
        flags=flags,
        plugin=plugin,
        v2_scraper=v2_scraper,
        ad_to_listing=lambda ad: ad,
    )


def test_default_impl_remains_v1_without_canary(monkeypatch):
    monkeypatch.setattr("app.services.source_execution_helpers.settings.enable_playwright", True)
    dispatch = _make_dispatch(src="mercadolivre", impl="v1", canary=False)
    ctx = SimpleNamespace(browser_fallback_enabled=True)

    out = dispatch("https://x", ctx)

    assert [row.external_id for row in out] == ["v1"]
    assert ctx._last_adapter_meta["impl"] == "v1"


def test_mercadolivre_uses_v2_when_canary_enabled_and_runtime_ready(monkeypatch):
    monkeypatch.setattr("app.services.source_execution_helpers.settings.enable_playwright", True)
    dispatch = _make_dispatch(src="mercadolivre", impl="v1", canary=True)
    ctx = SimpleNamespace(browser_fallback_enabled=True)

    out = dispatch("https://x", ctx)

    assert [row.external_id for row in out] == ["v2"]
    assert ctx._last_adapter_meta["impl"] == "v2_canary"


def test_canary_does_not_affect_other_sources(monkeypatch):
    monkeypatch.setattr("app.services.source_execution_helpers.settings.enable_playwright", True)
    dispatch = _make_dispatch(src="olx", impl="v1", canary=True)
    ctx = SimpleNamespace(browser_fallback_enabled=True)

    out = dispatch("https://x", ctx)

    assert [row.external_id for row in out] == ["v1"]
    assert ctx._last_adapter_meta["impl"] == "v1"


def test_canary_requires_playwright_and_browser_fallback(monkeypatch):
    monkeypatch.setattr("app.services.source_execution_helpers.settings.enable_playwright", False)
    dispatch = _make_dispatch(src="mercadolivre", impl="v1", canary=True)
    ctx = SimpleNamespace(browser_fallback_enabled=True)
    assert [row.external_id for row in dispatch("https://x", ctx)] == ["v1"]

    monkeypatch.setattr("app.services.source_execution_helpers.settings.enable_playwright", True)
    ctx2 = SimpleNamespace(browser_fallback_enabled=False)
    assert [row.external_id for row in dispatch("https://x", ctx2)] == ["v1"]
