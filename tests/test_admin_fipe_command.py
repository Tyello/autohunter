import asyncio
from datetime import datetime, timezone
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
        "confidence_label_counts": {"high": 3, "medium": 2, "low": 1},
        "detailed_counts": {"matched_high": 2, "ambiguous_high": 1, "ambiguous_medium": 2},
    })
    class _DB:
        def __enter__(self): return self
        def __exit__(self,*args): return False
    monkeypatch.setattr(admin_handlers_fipe, "SessionLocal", lambda: _DB())
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "resolver_status", "2026-05", "20")))
    assert "FIPE resolver status" in up.message.sent[-1]
    assert "matched: 2" in up.message.sent[-1]
    assert "Read-only" in up.message.sent[-1]


def test_render_admin_fipe_resolve_details():
    listing = SimpleNamespace(make="Honda", model="Civic Si", year=2015)
    msg = admin_handlers_fipe.render_admin_fipe_resolve({
        "reference_month": "2026-05",
        "status": "ambiguous",
        "ambiguity_reason": "segundo candidato também high e próximo",
        "best_candidate": {"model_name":"Civic Sedan SI 2.4 16V", "fipe_code":"015088-6", "model_year":2015, "fuel":"Gasolina", "price":95000, "confidence_score":86, "confidence_label":"high", "matched_tokens":["civic","si"], "missing_tokens":["2","4"], "warnings":["ano próximo (diferença de 1 ano)"]},
        "candidates": [
            {"model_name":"Civic Sedan SI 2.4 16V", "confidence_score":86, "confidence_label":"high", "model_year":2015, "fuel":"Gasolina", "fipe_code":"015088-6"},
            {"model_name":"Civic Sedan LXR 2.0", "confidence_score":82, "confidence_label":"high", "model_year":2015, "fuel":"Gasolina", "fipe_code":"001"},
        ],
    }, listing)
    assert "R$ 95.000,00" in msg
    assert "Outros candidatos" in msg
    assert "Motivo ambiguidade" in msg

def test_admin_fipe_plan_default_and_limit_cap(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    calls = {}

    def _fake(db, reference_month, limit=100, min_confidence=80):
        calls["reference_month"] = reference_month
        calls["limit"] = limit
        return {
            "reference_month": "2026-05",
            "sample_size": 100,
            "planned_inserts_count": 1,
            "would_update_count": 0,
            "already_exists_count": 0,
            "skipped_counts": {"ambiguous": 1, "no_match": 1, "insufficient_data": 0, "below_confidence": 0, "missing_price": 0, "missing_vehicle_key": 0, "already_exists": 0},
            "planned_inserts": [{"vehicle_key": "honda|civic|2015", "fipe_price": 95000, "confidence_score": 86, "model_name": "Civic"}],
        }

    class _Q:
        def __init__(self, value): self.value = value
        def order_by(self,*a,**k): return self
        def first(self): return self.value

    class _DB:
        def query(self,*a,**k): return _Q(("2026-05",))
        def __enter__(self): return self
        def __exit__(self,*a): return False

    monkeypatch.setattr(admin_handlers_fipe, "SessionLocal", lambda: _DB())
    monkeypatch.setattr(admin_handlers_fipe, "build_fipe_price_plan", _fake)

    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "plan")))
    assert calls["limit"] == 100
    assert "Read-only" in up.message.sent[-1]

    up2 = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up2, _ctx("fipe", "plan", "2026-05", "9999")))
    assert calls["reference_month"] == "2026-05"
    assert calls["limit"] == 500


def test_admin_fipe_apply_plan_default_dry(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    calls = {}

    def _fake(db, **kwargs):
        calls.update(kwargs)
        return {
            "reference_month": "2026-05", "dry_run": True, "sample_size": 100,
            "planned_inserts_count": 1, "would_update_count": 0, "inserted_count": 0, "updated_count": 0,
            "skipped_counts": {"ambiguous": 0, "no_match": 0, "insufficient_data": 0, "below_confidence": 0, "missing_price": 0, "missing_vehicle_key": 0, "already_exists": 0, "already_planned": 0},
        }

    class _Q:
        def __init__(self, value): self.value = value
        def order_by(self,*a,**k): return self
        def first(self): return self.value
    class _DB:
        def query(self,*a,**k): return _Q(("2026-05",))
        def __enter__(self): return self
        def __exit__(self,*a): return False
    monkeypatch.setattr(admin_handlers_fipe, "SessionLocal", lambda: _DB())
    monkeypatch.setattr(admin_handlers_fipe, "apply_fipe_price_plan", _fake)
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "apply_plan")))
    assert calls["dry_run"] is True


def test_admin_fipe_apply_plan_live_and_limit_cap(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    calls = {}

    def _fake(db, **kwargs):
        calls.update(kwargs)
        return {
            "reference_month": "2026-05", "dry_run": False, "sample_size": 500,
            "planned_inserts_count": 2, "would_update_count": 0, "inserted_count": 2, "updated_count": 0,
            "skipped_counts": {"ambiguous": 0, "no_match": 0, "insufficient_data": 0, "below_confidence": 0, "missing_price": 0, "missing_vehicle_key": 0, "already_exists": 0, "already_planned": 0},
        }

    class _Q:
        def __init__(self, value): self.value = value
        def order_by(self,*a,**k): return self
        def first(self): return self.value
    class _DB:
        def query(self,*a,**k): return _Q(("2026-05",))
        def __enter__(self): return self
        def __exit__(self,*a): return False
    monkeypatch.setattr(admin_handlers_fipe, "SessionLocal", lambda: _DB())
    monkeypatch.setattr(admin_handlers_fipe, "apply_fipe_price_plan", _fake)
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "apply_plan", "2026-05", "live", "9999")))
    assert calls["dry_run"] is False
    assert calls["limit"] == 500


def test_render_admin_fipe_apply_history_without_logs():
    msg = admin_handlers_fipe.render_admin_fipe_apply_history([])
    assert "Ainda não há histórico persistente de apply_plan." in msg


def test_render_admin_fipe_apply_history_dry_run():
    row = SimpleNamespace(
        created_at=datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
        message="fipe apply plan dry-run",
        payload={
            "reference_month": "2026-05",
            "planned_inserts_count": 10,
            "inserted_count": 0,
            "updated_count": 0,
            "sample_size": 100,
            "skipped_counts": {"no_match": 3, "ambiguous": 1},
        },
    )
    msg = admin_handlers_fipe.render_admin_fipe_apply_history([row])
    assert "FIPE apply_plan — histórico" in msg
    assert "dry-run" in msg
    assert "ref=2026-05" in msg


def test_render_admin_fipe_apply_history_live():
    row = SimpleNamespace(
        created_at=datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
        message="fipe apply plan live",
        payload={"reference_month": "2026-05", "planned_inserts_count": 2, "inserted_count": 2, "updated_count": 0, "sample_size": 200},
    )
    msg = admin_handlers_fipe.render_admin_fipe_apply_history([row])
    assert "live" in msg
    assert "ins=2" in msg


def test_render_admin_fipe_apply_history_error_and_legacy_payload():
    row = SimpleNamespace(
        created_at=datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
        message="fipe apply plan error",
        payload={"error": "x" * 200},
    )
    msg = admin_handlers_fipe.render_admin_fipe_apply_history([row])
    assert "error" in msg
    assert "err=" in msg
    assert "..." in msg

    row2 = SimpleNamespace(
        created_at=datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc),
        message="fipe apply plan dry-run",
        payload="legacy",
    )
    msg2 = admin_handlers_fipe.render_admin_fipe_apply_history([row2])
    assert "ref=-" in msg2


def test_admin_fipe_apply_history_dispatch_and_limit_cap(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    calls = {"limit": None}

    class _Q:
        def filter(self, *a, **k):
            return self
        def order_by(self, *a, **k):
            return self
        def limit(self, v):
            calls["limit"] = v
            return self
        def all(self):
            return []

    class _DB:
        def query(self, *a, **k):
            return _Q()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(admin_handlers_fipe, "SessionLocal", lambda: _DB())
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "apply_history", "999")))
    assert calls["limit"] == 20
    assert "Ainda não há histórico persistente" in up.message.sent[-1]
