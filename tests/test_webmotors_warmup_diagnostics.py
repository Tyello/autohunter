from app.scrapers.webmotors_ops import detect_webmotors_challenge
from app.bot.handlers_admin import _render_warmup_result
from pathlib import Path


def test_detect_webmotors_challenge_signals():
    d = detect_webmotors_challenge(html='Access to this page has been denied perimeterx px-captcha', title='Pressione e segure', final_url='https://x/challenge')
    assert d['still_challenge'] is True
    assert d['provider'] == 'perimeterx'
    assert d['reason'] in {'access_denied', 'press_and_hold', 'captcha'}


def test_detect_webmotors_challenge_clean():
    d = detect_webmotors_challenge(html='<html>ok</html>', title='Carros', final_url='https://www.webmotors.com.br/carros')
    assert d == {'still_challenge': False, 'provider': None, 'reason': None, 'signals': []}


def test_admin_render_warmup_blocked_and_safe_missing():
    txt = _render_warmup_result('webmotors', {'ok': True, 'still_challenge': True, 'challenge_provider': 'perimeterx', 'steps_completed': ['home']})
    assert 'still_challenge=True' in txt
    assert 'provider=perimeterx' in txt
    assert 'bloqueio anti-bot' in txt
    txt2 = _render_warmup_result('webmotors', {})
    assert 'ok=False' in txt2


def test_webmotors_default_extra_has_warmup_flag_false():
    content = Path("app/sources/builtins.py").read_text(encoding="utf-8")
    assert '"webmotors_warmup_behavior_enabled": False' in content
