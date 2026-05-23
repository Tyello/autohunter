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
