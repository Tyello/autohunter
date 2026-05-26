from app.models.source_config import SourceConfig
from app.services import source_configs_service as svc


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, row):
        self.row = row

    def execute(self, _q):
        return _FakeResult([self.row] if self.row else [])

    def flush(self):
        return None


def _row(extra=None):
    return SourceConfig(
        source="mercadolivre",
        is_enabled=True,
        sched_minutes=60,
        cooldown_minutes=0,
        rate_limit_seconds=0,
        proxy_server=None,
        browser_fallback_enabled=True,
        force_browser=False,
        extra=extra,
    )


def test_set_source_field_extra_merges_preserving_existing_keys():
    row = _row({"operational_role": "primary", "browser_block_resources": False})
    db = _FakeDB(row)

    out = svc.set_source_field(db, "mercadolivre", "extra", '{"mercadolivre_v2_canary_enabled":true,"impl":"v1"}')

    assert out.extra == {
        "operational_role": "primary",
        "browser_block_resources": False,
        "mercadolivre_v2_canary_enabled": True,
        "impl": "v1",
    }


def test_set_source_field_extra_overwrites_only_informed_keys():
    row = _row({"impl": "v1", "mercadolivre_v2_canary_enabled": True, "x": 1})
    db = _FakeDB(row)

    out = svc.set_source_field(db, "mercadolivre", "extra", '{"impl":"v2"}')

    assert out.extra["impl"] == "v2"
    assert out.extra["mercadolivre_v2_canary_enabled"] is True
    assert out.extra["x"] == 1


def test_set_source_field_extra_invalid_json_raises_clean_value_error():
    row = _row({})
    db = _FakeDB(row)

    try:
        svc.set_source_field(db, "mercadolivre", "extra", '{bad-json}')
        assert False, "expected ValueError"
    except ValueError as e:
        assert "JSON inválido" in str(e)


def test_set_source_field_extra_non_object_raises_value_error():
    row = _row({})
    db = _FakeDB(row)

    try:
        svc.set_source_field(db, "mercadolivre", "extra", '[]')
        assert False, "expected ValueError"
    except ValueError as e:
        assert "objeto JSON" in str(e)


def test_set_source_field_extra_false_updates_canary_false_and_null_removes_key():
    row = _row({"mercadolivre_v2_canary_enabled": True, "impl": "v1", "temp": "x"})
    db = _FakeDB(row)

    out = svc.set_source_field(
        db,
        "mercadolivre",
        "extra",
        '{"mercadolivre_v2_canary_enabled":false,"temp":null}',
    )

    assert out.extra["mercadolivre_v2_canary_enabled"] is False
    assert "temp" not in out.extra
