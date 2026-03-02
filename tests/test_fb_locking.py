import asyncio

from app.integrations.facebook.guards import UserOperationBusyError
from app.integrations.facebook.service import start_onboarding


class _DummyPage:
    async def goto(self, *args, **kwargs):
        await asyncio.sleep(0.05)


class _DummyContext:
    def __init__(self):
        self.pages = [_DummyPage()]

    async def new_page(self):
        return self.pages[0]


class _OpenCtx:
    def __init__(self, counter):
        self._counter = counter

    async def __aenter__(self):
        self._counter["opened"] += 1
        return _DummyContext()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_concurrent_start_returns_busy(monkeypatch):
    async def _run():
        counter = {"opened": 0}

        from app.integrations.facebook import service as svc

        monkeypatch.setattr(svc.fb_playwright_manager, "open_context", lambda **kwargs: _OpenCtx(counter))

        async def _call():
            try:
                await start_onboarding("u-lock", "/tmp/ignored", correlation_id="FB-AB12")
                return "ok"
            except UserOperationBusyError:
                return "busy"

        r1, r2 = await asyncio.gather(_call(), _call())
        assert sorted([r1, r2]) == ["busy", "ok"]
        assert counter["opened"] == 1

    asyncio.run(_run())
