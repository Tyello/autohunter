from datetime import timedelta

from app.models.source_config import SourceConfig
from app.services import source_configs_service as svc


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def execute(self, _q):
        self.calls += 1
        return _FakeResult(self.rows)


def _row(source='olx'):
    return SourceConfig(source=source, is_enabled=True, sched_minutes=5, cooldown_minutes=1, rate_limit_seconds=2, proxy_server=None, browser_fallback_enabled=False, force_browser=False, extra={'http_timeout_s': 10})


def test_cache_hot_path_reuses_snapshot_within_ttl():
    svc.invalidate_source_config_cache()
    db = _FakeDB([_row()])
    a = svc.get_source_config_snapshot(db, 'olx')
    b = svc.get_source_config_snapshot(db, 'olx')
    assert db.calls == 1
    assert a == b
    assert not isinstance(a, SourceConfig)


def test_cache_ttl_expired_reload(monkeypatch):
    svc.invalidate_source_config_cache()
    db = _FakeDB([_row()])
    svc.get_source_config_snapshot(db, 'olx')
    old = svc._cache_now() - timedelta(seconds=1)
    svc._CACHE_BY_SOURCE['olx'] = (old, svc._CACHE_BY_SOURCE['olx'][1])
    svc.get_source_config_snapshot(db, 'olx')
    assert db.calls == 2


def test_invalidate_source_config_cache_clears_entries():
    svc._CACHE_BY_SOURCE['olx'] = (svc._cache_now(), None)
    svc._CACHE_LIST = (svc._cache_now(), [])
    svc.invalidate_source_config_cache('olx')
    assert 'olx' not in svc._CACHE_BY_SOURCE
    svc.invalidate_source_config_cache()
    assert svc._CACHE_BY_SOURCE == {}
    assert svc._CACHE_LIST is None


def test_build_scrape_context_works_with_snapshot_cache(monkeypatch):
    svc.invalidate_source_config_cache()
    db = _FakeDB([_row('icarros')])
    ctx = svc.build_scrape_context(db, 'icarros')
    assert ctx.source == 'icarros'
    assert ctx.http_timeout_s == 10.0
