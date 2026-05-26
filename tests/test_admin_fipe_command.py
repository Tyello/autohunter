import asyncio
from types import SimpleNamespace

from app.bot import handlers_admin
from app.bot import admin_handlers_fipe


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(text)


class _Up:
    def __init__(self, chat_id):
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.message = _Msg()


def _ctx(*args):
    return SimpleNamespace(args=list(args))


def test_render_admin_fipe_coverage_has_expected_sections():
    msg = admin_handlers_fipe.render_admin_fipe_coverage(
        {
            "reference_month": "2026-05",
            "listings_with_fipe_keys": 320,
            "vehicle_keys_distinct": 48,
            "vehicle_keys_covered": 12,
            "coverage_pct": 25,
            "top_missing_keys": [{"vehicle_key": "honda|civic|2015", "count": 18}],
        }
    )
    assert "Competência: 2026-05" in msg
    assert "Cobertura: 12/48 keys (25%)" in msg
    assert "Top ausentes:" in msg
    assert "dry-run:" in msg
    assert "--apply" in msg


def test_admin_fipe_non_admin(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe")))
    assert "Sem permissão" in up.message.sent[-1]


def test_admin_fipe_coverage_defaults_and_limit_cap(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)

    calls = {}

    def _fake(db, reference_month=None, limit=20):
        calls["reference_month"] = reference_month
        calls["limit"] = limit
        return {
            "reference_month": "2026-05",
            "listings_with_fipe_keys": 320,
            "vehicle_keys_distinct": 48,
            "vehicle_keys_covered": 12,
            "coverage_pct": 25,
            "top_missing_keys": [{"vehicle_key": "honda|civic|2015", "count": 18}],
        }

    monkeypatch.setattr(admin_handlers_fipe, "build_fipe_coverage_report", _fake)
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "coverage")))
    assert calls["reference_month"] is None
    assert calls["limit"] == 20

    up2 = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up2, _ctx("fipe", "coverage", "2026-05", "999")))
    assert calls["reference_month"] == "2026-05"
    assert calls["limit"] == 50


def test_admin_fipe_coverage_value_error(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)

    def _fake(db, reference_month=None, limit=20):
        raise ValueError("reference_month inválido")

    monkeypatch.setattr(admin_handlers_fipe, "build_fipe_coverage_report", _fake)
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "coverage", "foo")))
    assert up.message.sent[-1] == "reference_month inválido"


def test_admin_dispatch_calls_new_fipe_handler(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    calls = {}

    async def _fake(update, raw_args):
        calls["raw_args"] = raw_args

    monkeypatch.setattr(handlers_admin, "admin_fipe", _fake)
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "coverage")))
    assert calls["raw_args"] == ["coverage"]


def test_admin_fipe_catalog_summary(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)

    class _Q:
        def __init__(self, value):
            self.value = value

        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def first(self):
            return self.value

        def count(self):
            return self.value

        def distinct(self):
            return self

    class _DB:
        def query(self, *args, **kwargs):
            name = getattr(args[0], "name", None) if args else None
            table = getattr(args[0], "__tablename__", None) if args else None
            if name == "reference_month":
                return _Q(("2026-05",))
            if name == "brand_name":
                return _Q(3)
            if name == "model_name":
                return _Q(10)
            if name == "model_year":
                return _Q(8)
            if table == "fipe_sync_runs":
                return _Q(SimpleNamespace(id="run-1", status="completed", source="external_pipeline"))
            return _Q(42)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(admin_handlers_fipe, "SessionLocal", lambda: _DB())
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "catalog", "2026-05")))
    assert "FIPE catálogo staging" in up.message.sent[-1]
    assert "Competência: 2026-05" in up.message.sent[-1]


def test_admin_fipe_catalog_invalid_month(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "catalog", "foo")))
    assert up.message.sent[-1] == "reference_month inválido; esperado YYYY-MM"


def test_admin_invalid_action_help_lists_fipe(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("comando_invalido")))
    msg = up.message.sent[-1]
    assert "Ação inválida" in msg
    assert "/admin fipe" in msg
    assert "/admin dedupe" in msg
    assert "/admin tracking" in msg
    assert "/admin digest" in msg



def test_admin_fipe_resolve_not_found(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)

    class _Q:
        def __init__(self, value): self.value=value
        def filter(self,*a,**k): return self
        def order_by(self,*a,**k): return self
        def first(self): return self.value

    class _DB:
        def query(self,*args,**kwargs):
            name = getattr(args[0], "name", None) if args else None
            if name == "reference_month": return _Q(("2026-05",))
            return _Q(None)
        def __enter__(self): return self
        def __exit__(self,*args): return False

    monkeypatch.setattr(admin_handlers_fipe, "SessionLocal", lambda: _DB())
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "resolve", "bad-id")))
    assert "Listing não encontrado" in up.message.sent[-1]


def test_admin_fipe_resolve_success(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)

    listing = SimpleNamespace(id="l1", make="Honda", model="Civic", year=2015)

    class _Q:
        def __init__(self, value): self.value=value
        def filter(self,*a,**k): return self
        def order_by(self,*a,**k): return self
        def first(self): return self.value

    class _DB:
        def query(self,*args,**kwargs):
            name = getattr(args[0], "name", None) if args else None
            if name == "reference_month": return _Q(("2026-05",))
            return _Q(listing)
        def __enter__(self): return self
        def __exit__(self,*args): return False

    monkeypatch.setattr(admin_handlers_fipe, "SessionLocal", lambda: _DB())
    monkeypatch.setattr(admin_handlers_fipe, "resolve_listing_to_fipe_candidates", lambda *a, **k: {
        "reference_month": "2026-05",
        "status": "matched",
        "candidates": [{"model_name":"Civic","confidence_score":90,"confidence_label":"high","fipe_code":"001","model_year":2015,"fuel":"Gasolina","price":95000,"reasons":["modelo compatível"]}],
        "best_candidate": {"model_name":"Civic","confidence_score":90,"confidence_label":"high","fipe_code":"001","model_year":2015,"fuel":"Gasolina","price":95000,"reasons":["modelo compatível"]},
    })
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "resolve", "l1")))
    assert "FIPE resolver" in up.message.sent[-1]
    assert "Status: matched" in up.message.sent[-1]


def test_admin_fipe_resolver_status(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(admin_handlers_fipe, "build_fipe_resolver_coverage_report", lambda *a, **k: {
        "reference_month": "2026-05", "sample_size": 10,
        "status_counts": {"matched": 2, "ambiguous": 3, "no_match": 4, "insufficient_data": 1},
    })
    class _DB:
        def __enter__(self): return self
        def __exit__(self,*args): return False
    monkeypatch.setattr(admin_handlers_fipe, "SessionLocal", lambda: _DB())
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "resolver_status", "2026-05", "20")))
    assert "FIPE resolver status" in up.message.sent[-1]
    assert "matched: 2" in up.message.sent[-1]
