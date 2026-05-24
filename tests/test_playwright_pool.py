from app.services.playwright_pool import _PlaywrightCore


class _FakePage:
    def __init__(self, responses):
        self._responses = list(responses)
        self.wait_calls = 0
        self.load_calls = 0

    def content(self):
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def wait_for_timeout(self, _ms):
        self.wait_calls += 1

    def wait_for_load_state(self, _state, timeout=0):
        self.load_calls += 1


def test_safe_page_content_retries_and_recovers():
    core = _PlaywrightCore()
    page = _FakePage([
        Exception("Page.content: Unable to retrieve content because the page is navigating and changing the content."),
        "<html>ok</html>",
    ])

    html = core._safe_page_content(page, attempts=5, wait_ms=10)

    assert html == "<html>ok</html>"
    assert page.wait_calls == 1
    assert page.load_calls == 1


def test_safe_page_content_raises_last_exception_when_persistent():
    core = _PlaywrightCore()
    err = Exception("Execution context was destroyed")
    page = _FakePage([err, Exception("Execution context was destroyed"), Exception("Execution context was destroyed")])

    try:
        core._safe_page_content(page, attempts=3, wait_ms=10)
        assert False, "expected exception"
    except Exception as exc:
        assert "Execution context was destroyed" in str(exc)
    assert page.wait_calls == 2


def test_safe_page_content_non_retryable_error_raises_immediately():
    core = _PlaywrightCore()
    page = _FakePage([ValueError("boom")])

    try:
        core._safe_page_content(page, attempts=5, wait_ms=10)
        assert False, "expected exception"
    except ValueError as exc:
        assert str(exc) == "boom"
    assert page.wait_calls == 0
    assert page.load_calls == 0


class _FakeCtx:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_invalidate_contexts_removes_only_target_and_storage(tmp_path, monkeypatch):
    core = _PlaywrightCore()
    ml_ctx = _FakeCtx()
    olx_ctx = _FakeCtx()
    core._contexts = {
        ("__no_proxy__", "mercadolivre", False): ml_ctx,
        ("__no_proxy__", "olx", False): olx_ctx,
    }
    core._ctx_last_used = {k: 1.0 for k in core._contexts.keys()}

    monkeypatch.setattr("app.services.playwright_pool.playwright_storage_dir", lambda: tmp_path)
    ml_storage = tmp_path / "storage_mercadolivre____no_proxy__.json"
    other_storage = tmp_path / "storage_olx____no_proxy__.json"
    ml_storage.write_text("{}", encoding="utf-8")
    other_storage.write_text("{}", encoding="utf-8")

    out = core.invalidate_contexts(source="mercadolivre", proxy_server=None, block_resources=False, clear_storage=True)

    assert out["removed_contexts"] == 1
    assert ml_ctx.closed is True
    assert olx_ctx.closed is False
    assert ml_storage.exists() is False
    assert other_storage.exists() is True


def test_invalidate_contexts_no_storage_no_fail(tmp_path, monkeypatch):
    core = _PlaywrightCore()
    monkeypatch.setattr("app.services.playwright_pool.playwright_storage_dir", lambda: tmp_path)
    out = core.invalidate_contexts(source="mercadolivre", clear_storage=True)
    assert out["removed_contexts"] == 0


def test_playwright_pool_invalidate_contexts_delegates_to_worker_call(monkeypatch):
    from app.services.playwright_pool import PlaywrightPool

    pool = PlaywrightPool()
    called = {}

    def _fake_call(name, *, hard_timeout_s, **kwargs):
        called["name"] = name
        called["hard_timeout_s"] = hard_timeout_s
        called["kwargs"] = kwargs
        return {"removed_contexts": 1}

    monkeypatch.setattr(pool, "_call", _fake_call)

    out = pool.invalidate_contexts(
        source="mercadolivre",
        proxy_server="http://proxy:8080",
        block_resources=False,
        clear_storage=True,
    )

    assert out == {"removed_contexts": 1}
    assert called["name"] == "invalidate_contexts"
    assert called["hard_timeout_s"] == 10.0
    assert called["kwargs"] == {
        "source": "mercadolivre",
        "proxy_server": "http://proxy:8080",
        "block_resources": False,
        "clear_storage": True,
    }


def test_reset_browser_state_for_source_calls_backend_invalidate(monkeypatch):
    from types import SimpleNamespace
    from app.services import browser_fetcher

    calls = {}

    class _Backend:
        def invalidate_contexts(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr(browser_fetcher, "_get_backend", lambda: _Backend())
    ctx = SimpleNamespace(source="mercadolivre", proxy_server="http://proxy:8080", browser_block_resources=None)

    browser_fetcher.reset_browser_state_for_source(
        "mercadolivre",
        ctx,
        block_resources=False,
        clear_storage=True,
    )

    assert calls == {
        "source": "mercadolivre",
        "proxy_server": "http://proxy:8080",
        "block_resources": False,
        "clear_storage": True,
    }
