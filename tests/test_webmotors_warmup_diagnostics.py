import asyncio

from app.scrapers.webmotors_ops import detect_webmotors_challenge
from app.bot import handlers_admin
from app.bot.handlers_admin import _render_warmup_result


def test_detect_webmotors_challenge_signals():
    d = detect_webmotors_challenge(html='Access to this page has been denied perimeterx px-captcha', title='Pressione e segure', final_url='https://x/challenge')
    assert d['still_challenge'] is True
    assert d['provider'] == 'perimeterx'


def test_detect_webmotors_challenge_clean():
    d = detect_webmotors_challenge(html='<html>ok</html>', title='Carros', final_url='https://www.webmotors.com.br/carros')
    assert d == {'still_challenge': False, 'provider': None, 'reason': None, 'signals': []}


def test_admin_render_warmup_shows_signals_and_error():
    txt = _render_warmup_result('webmotors', {
        'ok': False,
        'still_challenge': True,
        'challenge_provider': 'perimeterx',
        'challenge_signals': ['access_denied', 'press_and_hold'],
        'error': 'boom happened',
        'steps_completed': ['home'],
    })
    assert 'signals=access_denied,press_and_hold' in txt
    assert 'error=boom happened' in txt


def test_admin_warmup_uses_to_thread(monkeypatch):
    calls = {'to_thread': 0}

    class _Msg:
        sent = []
        async def reply_text(self, text):
            self.sent.append(text)

    class _Update:
        message = _Msg()

    class _Cfg:
        extra = {}
        proxy_server = None

    class _CtxMgr:
        def __enter__(self):
            return object()
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(handlers_admin, 'SessionLocal', lambda: _CtxMgr())
    monkeypatch.setattr(handlers_admin, 'ensure_source_configs', lambda _db: None)
    monkeypatch.setattr(handlers_admin, 'get_source_config', lambda _db, _s: _Cfg())

    async def _fake_to_thread(fn, *args, **kwargs):
        calls['to_thread'] += 1
        return fn(*args, **kwargs)

    class _Res:
        ok = True
        data = {'ok': True, 'steps_completed': []}
        error = ''

    monkeypatch.setattr(handlers_admin.asyncio, 'to_thread', _fake_to_thread)
    monkeypatch.setattr(handlers_admin, 'warmup_source', lambda **_k: _Res())

    asyncio.run(handlers_admin._admin_warmup(_Update(), ['webmotors']))
    assert calls['to_thread'] == 1


def test_webmotors_default_extra_has_warmup_flag_false():
    from pathlib import Path
    content = Path('app/sources/builtins.py').read_text(encoding='utf-8')
    assert '"webmotors_warmup_behavior_enabled": False' in content


def test_warmup_sync_consent_clicked(monkeypatch):
    from app.services.playwright_pool import _PlaywrightCore

    class _El:
        def click(self, timeout=0):
            return None

    class _Page:
        url = 'https://www.webmotors.com.br/carros'
        def goto(self, *a, **k):
            return None
        def wait_for_timeout(self, *_a, **_k):
            return None
        def evaluate(self, *_a, **_k):
            return None
        class mouse:
            @staticmethod
            def move(*_a, **_k):
                return None
        def query_selector(self, selector):
            return _El() if "button:has-text('aceitar')" in selector else None
        def content(self):
            return 'ok'
        def title(self):
            return 'ok'

    class _Ctx:
        def new_page(self):
            return _Page()
        def storage_state(self, path=None):
            return None
        def close(self):
            return None

    class _Browser:
        def new_context(self, **_k):
            return _Ctx()

    core = _PlaywrightCore()
    monkeypatch.setattr(core, '_get_or_create_browser', lambda _p: _Browser())
    monkeypatch.setattr(core, '_storage_path', lambda *_a: '/tmp/warmup_test.json')
    core._contexts = {('__no_proxy__', 'webmotors', True): object()}
    core._ctx_last_used = {('__no_proxy__', 'webmotors', True): 1.0}
    out = core.warmup(source='webmotors', proxy_server=None, behavior={'webmotors_warmup_behavior_enabled': True})
    assert 'consent_clicked' in out.get('steps_completed', [])


def test_warmup_behavior_disabled_skips_substeps(monkeypatch):
    from app.services.playwright_pool import _PlaywrightCore

    class _Page:
        url = 'https://www.webmotors.com.br/carros'
        def goto(self, *a, **k): return None
        def wait_for_timeout(self, *_a, **_k): return None
        def evaluate(self, *_a, **_k): return None
        class mouse:
            @staticmethod
            def move(*_a, **_k): return None
        def query_selector(self, _selector): return None
        def content(self): return 'ok'
        def title(self): return 'ok'

    class _Ctx:
        def new_page(self): return _Page()
        def storage_state(self, path=None): return None
        def close(self): return None

    class _Browser:
        def new_context(self, **_k): return _Ctx()

    core = _PlaywrightCore()
    monkeypatch.setattr(core, '_get_or_create_browser', lambda _p: _Browser())
    monkeypatch.setattr(core, '_storage_path', lambda *_a: '/tmp/warmup_test.json')
    out = core.warmup(source='webmotors', proxy_server=None, behavior={'webmotors_warmup_behavior_enabled': False})
    steps = out.get('steps_completed', [])
    assert 'scroll' not in steps
    assert 'mouse' not in steps
    assert 'consent_attempted' not in steps and 'consent_clicked' not in steps
    assert 'extra_wait' not in steps


def test_warmup_none_subflags_do_not_disable_defaults(monkeypatch):
    from app.services.playwright_pool import _PlaywrightCore

    class _Page:
        url = 'https://www.webmotors.com.br/carros'
        wait_calls = []
        def goto(self, *a, **k): return None
        def wait_for_timeout(self, ms, **_k): self.wait_calls.append(ms)
        def evaluate(self, *_a, **_k): return None
        class mouse:
            @staticmethod
            def move(*_a, **_k): return None
        def query_selector(self, _selector): return None
        def content(self): return 'ok'
        def title(self): return 'ok'

    class _Ctx:
        def __init__(self):
            self.page = _Page()
        def new_page(self): return self.page
        def storage_state(self, path=None): return None
        def close(self): return None

    class _Browser:
        def __init__(self):
            self.ctx = _Ctx()
        def new_context(self, **_k): return self.ctx

    browser = _Browser()
    core = _PlaywrightCore()
    monkeypatch.setattr(core, '_get_or_create_browser', lambda _p: browser)
    monkeypatch.setattr(core, '_storage_path', lambda *_a: '/tmp/warmup_test.json')
    out = core.warmup(
        source='webmotors',
        proxy_server=None,
        behavior={
            'webmotors_warmup_behavior_enabled': True,
            'webmotors_warmup_scroll_enabled': None,
            'webmotors_warmup_mouse_enabled': None,
            'webmotors_warmup_consent_enabled': None,
            'webmotors_warmup_extra_wait_ms': None,
        },
    )
    steps = out.get('steps_completed', [])
    assert 'scroll' in steps
    assert 'mouse' in steps
    assert ('consent_attempted' in steps) or ('consent_clicked' in steps)
    assert 'extra_wait' in steps
    assert 1500 in browser.ctx.page.wait_calls


def test_warmup_subflag_false_and_wait_clamp(monkeypatch):
    from app.services.playwright_pool import _PlaywrightCore

    class _Page:
        url = 'https://www.webmotors.com.br/carros'
        wait_calls = []
        def goto(self, *a, **k): return None
        def wait_for_timeout(self, ms, **_k): self.wait_calls.append(ms)
        def evaluate(self, *_a, **_k): return None
        class mouse:
            @staticmethod
            def move(*_a, **_k): return None
        def query_selector(self, _selector): return None
        def content(self): return 'ok'
        def title(self): return 'ok'

    class _Ctx:
        def __init__(self):
            self.page = _Page()
        def new_page(self): return self.page
        def storage_state(self, path=None): return None
        def close(self): return None

    class _Browser:
        def __init__(self):
            self.ctx = _Ctx()
        def new_context(self, **_k): return self.ctx

    browser = _Browser()
    core = _PlaywrightCore()
    monkeypatch.setattr(core, '_get_or_create_browser', lambda _p: browser)
    monkeypatch.setattr(core, '_storage_path', lambda *_a: '/tmp/warmup_test.json')
    out = core.warmup(
        source='webmotors',
        proxy_server=None,
        behavior={
            'webmotors_warmup_behavior_enabled': True,
            'webmotors_warmup_scroll_enabled': False,
            'webmotors_warmup_extra_wait_ms': 99999,
        },
    )
    steps = out.get('steps_completed', [])
    assert 'scroll' not in steps
    assert 'extra_wait' in steps
    assert 5000 in browser.ctx.page.wait_calls
