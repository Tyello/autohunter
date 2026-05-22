from types import SimpleNamespace

from app.models.source_config import SourceConfig
from app.services import source_configs_service as svc
from app.services import browser_fetcher
from app.scrapers.scraper_base import fetcher as unified_fetcher
from app.sources.registry import list_sources
from app.sources.types import ScrapeContext
from app.services.playwright_pool import _PlaywrightCore


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _q):
        return _FakeResult(self.rows)


def _cfg(extra: dict | None) -> SourceConfig:
    return SourceConfig(
        source="webmotors",
        is_enabled=True,
        sched_minutes=5,
        cooldown_minutes=1,
        rate_limit_seconds=2,
        proxy_server=None,
        browser_fallback_enabled=True,
        force_browser=False,
        extra=extra,
    )


def test_build_scrape_context_browser_block_resources_values():
    svc.invalidate_source_config_cache()
    assert svc.build_scrape_context(_FakeDB([_cfg({"browser_block_resources": False})]), "webmotors").browser_block_resources is False
    svc.invalidate_source_config_cache()
    assert svc.build_scrape_context(_FakeDB([_cfg({"browser_block_resources": True})]), "webmotors").browser_block_resources is True
    svc.invalidate_source_config_cache()
    assert svc.build_scrape_context(_FakeDB([_cfg({})]), "webmotors").browser_block_resources is None
    svc.invalidate_source_config_cache()
    assert svc.build_scrape_context(_FakeDB([_cfg({"browser_block_resources": "false"})]), "webmotors").browser_block_resources is False
    svc.invalidate_source_config_cache()
    assert svc.build_scrape_context(_FakeDB([_cfg({"browser_block_resources": "true"})]), "webmotors").browser_block_resources is True


def test_unified_fetch_browser_passes_block_resources(monkeypatch):
    captured = {}

    class _Mgr:
        def fetch_html(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(html="ok", final_url=kwargs["url"])

    monkeypatch.setattr("app.scrapers.shared.browser_manager.get_browser_manager", lambda: _Mgr())

    ctx = ScrapeContext(source="webmotors", force_browser=True, browser_block_resources=False)
    result = unified_fetcher.unified_fetch("https://example.com", ctx, "webmotors")
    assert result.method == "browser"
    assert captured["block_resources"] is False


def test_browser_fetcher_passes_block_resources(monkeypatch):
    calls = {"fetch": None, "fetch_json": None}

    class _Backend:
        def fetch(self, url, **kwargs):
            calls["fetch"] = kwargs
            return SimpleNamespace(html="<html></html>", final_url=url)

        def fetch_json(self, url, **kwargs):
            calls["fetch_json"] = kwargs
            return SimpleNamespace(data={"ok": True}, final_url=url, data_url=url + "/api")

    monkeypatch.setattr(browser_fetcher, "_get_backend", lambda: _Backend())

    ctx_false = ScrapeContext(source="webmotors", browser_block_resources=False)
    browser_fetcher.fetch_html_browser("https://example.com", ctx=ctx_false, min_delay_ms=0, max_delay_ms=0)
    assert calls["fetch"]["block_resources"] is False

    ctx_true = ScrapeContext(source="olx", browser_block_resources=True)
    browser_fetcher.fetch_json_browser("https://example.com", ctx=ctx_true, min_delay_ms=0, max_delay_ms=0)
    assert calls["fetch_json"]["block_resources"] is True


def test_builtins_defaults_for_non_blocking_sources():
    by_name = {p.name: p for p in list_sources()}
    for src in ("webmotors", "icarros", "mobiauto", "facebook_marketplace"):
        assert by_name[src].default_extra.get("browser_block_resources") is False


def test_builtins_gogarage_kavak_do_not_set_non_blocking_default():
    by_name = {p.name: p for p in list_sources()}
    assert "browser_block_resources" not in by_name["gogarage"].default_extra
    assert "browser_block_resources" not in by_name["kavak"].default_extra


def test_block_heavy_resources_respects_false_flag():
    core = _PlaywrightCore()

    class _Page:
        def __init__(self):
            self.called = 0

        def route(self, *_args, **_kwargs):
            self.called += 1

    page = _Page()
    core._block_heavy_resources(page, source="olx", block_resources=False)
    assert page.called == 0


def test_warmup_invalidates_contexts_without_name_error(monkeypatch):
    core = _PlaywrightCore()
    closed = []

    class _OldCtx:
        def __init__(self, name):
            self.name = name

        def close(self):
            closed.append(self.name)

    class _WarmupCtx:
        def new_page(self):
            class _Page:
                url = "https://example.com"

                def goto(self, *_args, **_kwargs):
                    return None

                def wait_for_timeout(self, *_args, **_kwargs):
                    return None

                def content(self):
                    return "<html></html>"

                def title(self):
                    return "ok"

            return _Page()

        def storage_state(self, path):
            return path

        def close(self):
            return None

    class _Browser:
        def new_context(self, **_kwargs):
            return _WarmupCtx()

    core._contexts = {
        ("proxyA", "webmotors", True): _OldCtx("t"),
        ("proxyA", "webmotors", False): _OldCtx("f"),
        ("proxyA", "olx", True): _OldCtx("other_source"),
        ("proxyB", "webmotors", True): _OldCtx("other_proxy"),
    }
    core._ctx_last_used = {
        ("proxyA", "webmotors", True): 1.0,
        ("proxyA", "webmotors", False): 1.0,
        ("proxyA", "olx", True): 1.0,
        ("proxyB", "webmotors", True): 1.0,
    }

    monkeypatch.setattr(core, "_get_or_create_browser", lambda _proxy: _Browser())

    out = core.warmup(source="webmotors", proxy_server="proxyA", url="https://www.webmotors.com.br/", timeout_ms=10)
    assert out["ok"] is True
    assert ("proxyA", "webmotors", True) not in core._contexts
    assert ("proxyA", "webmotors", False) not in core._contexts
    assert ("proxyA", "olx", True) in core._contexts
    assert ("proxyB", "webmotors", True) in core._contexts
    assert set(closed) == {"t", "f"}
