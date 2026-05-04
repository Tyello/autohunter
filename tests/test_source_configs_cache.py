from app.services import source_configs_service as svc


def test_invalidate_source_config_cache_clears_entries():
    svc._CACHE_BY_SOURCE['olx'] = (svc._cache_now(), None)
    svc._CACHE_LIST = (svc._cache_now(), [])
    svc.invalidate_source_config_cache()
    assert svc._CACHE_BY_SOURCE == {}
    assert svc._CACHE_LIST is None
