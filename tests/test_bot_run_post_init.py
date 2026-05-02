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


def test_main_registers_menu_and_start_handlers(monkeypatch):
    called_commands = []

    class _FakeApp:
        def add_handler(self, handler):
            if hasattr(handler, "commands"):
                called_commands.extend(list(handler.commands))

        def add_error_handler(self, _handler):
            return None

        def run_polling(self, **_kwargs):
            return None

    class _Builder:
        def token(self, _token):
            return self

        def post_init(self, _post_init):
            return self

        def build(self):
            return _FakeApp()

    monkeypatch.setattr(run.settings, "telegram_bot_token", "token")
    monkeypatch.setattr(run.settings, "playwright_smoke_on_boot", False)
    monkeypatch.setattr(run.Application, "builder", lambda: _Builder())

    run.main()

    assert "start" in called_commands
    assert "menu" in called_commands
