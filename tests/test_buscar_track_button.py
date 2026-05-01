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


def _run_buscar(monkeypatch, wishlists):
    monkeypatch.setattr(handlers, 'SessionLocal', lambda: _Session())
    monkeypatch.setattr(handlers, 'get_or_create_user_by_chat', lambda *_: types.SimpleNamespace(id='u1'))
    monkeypatch.setattr(handlers, 'manual_search', lambda *_args, **_kwargs: [types.SimpleNamespace(id='c1', title='t', price=1, source='olx', url='https://x', external_id='e1', thumbnail_url=None)])
    monkeypatch.setattr(handlers, 'list_wishlists', lambda *_: wishlists)
    monkeypatch.setattr(handlers, 'score_ad', lambda *_: types.SimpleNamespace(total=0, to_dict=lambda :{}))
    sent=[]
    async def _send_listing_message(_update, **kwargs): sent.append(kwargs)
    monkeypatch.setattr(handlers, 'send_listing_message', _send_listing_message)
    asyncio.run(handlers.cmd_buscar(_Update(), types.SimpleNamespace(args=['civic'])))
    return sent[0]['reply_markup'].inline_keyboard


def test_buscar_zero_wishlist_has_no_track_button(monkeypatch):
    rows = _run_buscar(monkeypatch, wishlists=[])
    labels = [b.text for r in rows for b in r]
    assert '⭐ Rastrear' not in labels


def test_buscar_one_wishlist_adds_single_track_button(monkeypatch):
    rows = _run_buscar(monkeypatch, wishlists=[types.SimpleNamespace(id='w1', query='civic si')])
    buttons = [b for r in rows for b in r if b.text.startswith('⭐')]
    assert len(buttons) == 1
    assert buttons[0].text == '⭐ Rastrear'
    assert buttons[0].callback_data == 'TRACK:ADDWL:w1:c1'


def test_buscar_two_wishlists_adds_named_buttons(monkeypatch):
    rows = _run_buscar(monkeypatch, wishlists=[types.SimpleNamespace(id='w1', query='civic si'), types.SimpleNamespace(id='w2', query='miata')])
    buttons = [b for r in rows for b in r if b.text.startswith('⭐')]
    assert [b.text for b in buttons] == ['⭐ Rastrear em civic si', '⭐ Rastrear em miata']
    assert buttons[0].callback_data == 'TRACK:ADDWL:w1:c1'
    assert buttons[1].callback_data == 'TRACK:ADDWL:w2:c1'


def test_buscar_three_wishlists_adds_three_buttons(monkeypatch):
    rows = _run_buscar(monkeypatch, wishlists=[types.SimpleNamespace(id='w1', query='a'), types.SimpleNamespace(id='w2', query='b'), types.SimpleNamespace(id='w3', query='c')])
    buttons = [b for r in rows for b in r if b.text.startswith('⭐')]
    assert len(buttons) == 3
    assert all(b.text.startswith('⭐ Rastrear em ') for b in buttons)


def test_buscar_more_than_three_uses_choose_button(monkeypatch):
    rows = _run_buscar(monkeypatch, wishlists=[types.SimpleNamespace(id='w1', query='a'), types.SimpleNamespace(id='w2', query='b'), types.SimpleNamespace(id='w3', query='c'), types.SimpleNamespace(id='w4', query='d')])
    buttons = [b for r in rows for b in r if b.text.startswith('⭐')]
    assert len(buttons) == 1
    assert buttons[0].text == '⭐ Escolher wishlist'
    assert buttons[0].callback_data == 'TRACK:CHOOSE:c1'


def test_buscar_track_callbacks_fit_64_bytes(monkeypatch):
    wl_id = 'w' * 20
    listing_id = 'c' * 32
    monkeypatch.setattr(handlers, 'SessionLocal', lambda: _Session())
    monkeypatch.setattr(handlers, 'get_or_create_user_by_chat', lambda *_: types.SimpleNamespace(id='u1'))
    monkeypatch.setattr(handlers, 'manual_search', lambda *_args, **_kwargs: [types.SimpleNamespace(id=listing_id, title='t', price=1, source='olx', url='https://x', external_id='e1', thumbnail_url=None)])
    monkeypatch.setattr(handlers, 'list_wishlists', lambda *_: [types.SimpleNamespace(id=wl_id, query='q')])
    monkeypatch.setattr(handlers, 'score_ad', lambda *_: types.SimpleNamespace(total=0, to_dict=lambda :{}))
    sent=[]
    async def _send_listing_message(_update, **kwargs): sent.append(kwargs)
    monkeypatch.setattr(handlers, 'send_listing_message', _send_listing_message)
    asyncio.run(handlers.cmd_buscar(_Update(), types.SimpleNamespace(args=['civic'])))
    rows = sent[0]['reply_markup'].inline_keyboard
    for btn in [b for r in rows for b in r if b.callback_data]:
        assert len(btn.callback_data.encode('utf-8')) <= 64


def test_buscar_never_uses_addwi(monkeypatch):
    wl_id = 'w' * 40
    listing_id = 'c' * 40
    rows = _run_buscar(monkeypatch, wishlists=[types.SimpleNamespace(id=wl_id, query='long wishlist')])
    for btn in [b for r in rows for b in r if b.callback_data]:
        assert not btn.callback_data.startswith('TRACK:ADDWI:')


def test_buscar_long_callback_uses_addt(monkeypatch):
    wl_id = 'w' * 40
    listing_id = 'c' * 40
    monkeypatch.setattr(handlers, 'SessionLocal', lambda: _Session())
    monkeypatch.setattr(handlers, 'get_or_create_user_by_chat', lambda *_: types.SimpleNamespace(id='u1'))
    monkeypatch.setattr(handlers, 'manual_search', lambda *_args, **_kwargs: [types.SimpleNamespace(id=listing_id, title='t', price=1, source='olx', url='https://x', external_id='e1', thumbnail_url=None)])
    monkeypatch.setattr(handlers, 'list_wishlists', lambda *_: [types.SimpleNamespace(id=wl_id, query='q')])
    monkeypatch.setattr(handlers, 'score_ad', lambda *_: types.SimpleNamespace(total=0, to_dict=lambda :{}))
    sent=[]
    async def _send_listing_message(_update, **kwargs): sent.append(kwargs)
    monkeypatch.setattr(handlers, 'send_listing_message', _send_listing_message)
    asyncio.run(handlers.cmd_buscar(_Update(), types.SimpleNamespace(args=['civic'])))
    rows = sent[0]['reply_markup'].inline_keyboard
    track = [b for r in rows for b in r if b.text.startswith('⭐')][0]
    assert track.callback_data.startswith('TRACK:ADDT:')
    assert len(track.callback_data.encode('utf-8')) <= 64
