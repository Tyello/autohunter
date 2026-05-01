from __future__ import annotations
import asyncio, types
from app.bot import handlers


class _Session:
    def __enter__(self): return self
    def __exit__(self,*_): return None

class _Msg:
    async def reply_text(self,*a,**k): pass

class _Update:
    def __init__(self):
        self.effective_chat=types.SimpleNamespace(id=1)
        self.effective_user=types.SimpleNamespace(username='u')
        self.message=_Msg(); self.effective_message=self.message


def _run_buscar(monkeypatch):
    monkeypatch.setattr(handlers, 'SessionLocal', lambda: _Session())
    monkeypatch.setattr(handlers, 'get_or_create_user_by_chat', lambda *_: types.SimpleNamespace(id='u1'))
    monkeypatch.setattr(handlers, 'manual_search', lambda *_args, **_kwargs: [types.SimpleNamespace(id='c1', title='t', price=1, source='olx', url='https://x', external_id='e1', thumbnail_url=None)])
    monkeypatch.setattr(handlers, 'score_ad', lambda *_: types.SimpleNamespace(total=0, to_dict=lambda :{}))
    sent=[]
    async def _send_listing_message(_update, **kwargs): sent.append(kwargs)
    monkeypatch.setattr(handlers, 'send_listing_message', _send_listing_message)
    asyncio.run(handlers.cmd_buscar(_Update(), types.SimpleNamespace(args=['civic'])))
    return sent[0]['reply_markup'].inline_keyboard


def test_buscar_has_no_track_buttons(monkeypatch):
    rows = _run_buscar(monkeypatch)
    labels = [b.text for r in rows for b in r]
    assert all(not label.startswith('⭐') for label in labels)


def test_buscar_still_shows_listing_open_button(monkeypatch):
    rows = _run_buscar(monkeypatch)
    buttons = [b for r in rows for b in r]
    assert buttons
    assert any(getattr(b, 'url', None) for b in buttons)
