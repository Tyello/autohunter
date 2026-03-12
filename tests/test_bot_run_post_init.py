from __future__ import annotations

import asyncio
from types import SimpleNamespace

from telegram.error import TimedOut

from app.bot import run


def test_post_init_ignores_timeout_from_setup_bot_commands(monkeypatch):
    called = {"setup": 0, "jobs": 0}

    async def _fake_setup(_bot):
        called["setup"] += 1
        raise TimedOut("Timed out")

    class _FakeJobQueue:
        def run_repeating(self, *args, **kwargs):
            called["jobs"] += 1

    app = SimpleNamespace(bot=object(), job_queue=_FakeJobQueue())

    monkeypatch.setattr(run, "setup_bot_commands", _fake_setup)
    monkeypatch.setattr(run.settings, "enable_sender_in_bot", False)

    asyncio.run(run._post_init(app))

    assert called["setup"] == 1
    assert called["jobs"] == 0
