from app.sources.auctions.diagnostics import build_auction_source_fetch_diagnostics


class _Resp:
    def __init__(self, status_code=200, url='https://x/list', headers=None, text=''):
        self.status_code = status_code
        self.url = url
        self.headers = headers or {"content-type": "text/html"}
        self.text = text


def test_diagnostics_scripts_and_js_hints():
    html = '<html><head><title>T</title></head><body><div id="react-root"></div><script>window.__NEXT_DATA__={}</script></body></html>'
    d = build_auction_source_fetch_diagnostics(_Resp(text=html), html, 'https://x/list', reason='no_public_lot_cards_found')
    assert d['status_code'] == 200
    assert d['hints']['has_script_tags'] is True
    assert d['hints']['possible_js_app'] is True


def test_diagnostics_403_forbidden():
    d = build_auction_source_fetch_diagnostics(_Resp(status_code=403, text='forbidden'), 'forbidden', 'https://x/list', reason='forbidden_403')
    assert d['status_code'] == 403
    assert d['reason'] == 'forbidden_403'


def test_preview_truncated_and_sanitized():
    html = '<script>alert(1)</script>' + ('a' * 5000)
    d = build_auction_source_fetch_diagnostics(_Resp(text=html), html, 'https://x/list')
    assert len(d['html_preview']) <= 900
    assert 'alert(1)' not in d['html_preview']
