from __future__ import annotations

import asyncio

import pytest
from telegram.error import BadRequest

from app.bot.handlers_wishlist_ui import _safe_answer_callback


class _FakeCallbackQuery:
    def __init__(self, exc: Exception | None = None):
        self.exc = exc
        self.calls = 0

    async def answer(self):
        self.calls += 1
        if self.exc is not None:
            raise self.exc


def test_safe_answer_callback_ignores_expired_query():
    q = _FakeCallbackQuery(BadRequest("Query is too old and response timeout expired or query id is invalid"))

    asyncio.run(_safe_answer_callback(q))

    assert q.calls == 1


def test_safe_answer_callback_reraises_other_bad_request():
    q = _FakeCallbackQuery(BadRequest("message is not modified"))

    with pytest.raises(BadRequest):
        asyncio.run(_safe_answer_callback(q))
