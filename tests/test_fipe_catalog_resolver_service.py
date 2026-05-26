from types import SimpleNamespace

from app.services import fipe_catalog_resolver_service as svc


def _entry(**kwargs):
    base = dict(
        id="e1",
        fipe_code="001",
        brand_name="Honda",
        model_name="Civic Sedan LXR 2.0 Flex",
        model_year=2015,
        fuel="Gasolina",
        price=95000,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_normalize_vehicle_text():
    assert svc.normalize_vehicle_text("  Cívic   EXR ") == "civic exr"


def test_build_listing_query():
    listing = SimpleNamespace(make="Honda", model="Civic", version="EXR", year=2015, fuel_type="Gasolina", transmission=None, body_type=None, doors=4)
    q = svc.build_listing_fipe_query(listing)
    assert q["make"] == "honda"
    assert q["model"] == "civic"
    assert q["year"] == 2015


def test_score_exact_match_high():
    q = {"make": "honda", "model": "civic", "version": "lxr", "year": 2015, "fuel_type": "gasolina"}
    scored = svc.score_fipe_candidate(listing_query=q, catalog_entry=_entry())
    assert scored["confidence_label"] == "high"
    assert scored["confidence_score"] >= 80


def test_score_year_mismatch_penalty():
    q = {"make": "honda", "model": "civic", "version": "lxr", "year": 2015, "fuel_type": "gasolina"}
    scored = svc.score_fipe_candidate(listing_query=q, catalog_entry=_entry(model_year=2016))
    assert "ano divergente" in scored["warnings"]
    assert scored["confidence_score"] < 80


def test_resolve_ambiguous(monkeypatch):
    listing = SimpleNamespace(id="l1", make="Honda", model="Civic", version="", year=2015, fuel_type="Gasolina")
    monkeypatch.setattr(svc, "find_fipe_catalog_candidates", lambda *a, **k: [_entry(id="e1", model_name="Civic EXR"), _entry(id="e2", model_name="Civic LXR")])
    out = svc.resolve_listing_to_fipe_candidates(None, listing=listing, reference_month="2026-05", limit=10)
    assert out["status"] == "ambiguous"


def test_resolve_no_match(monkeypatch):
    listing = SimpleNamespace(id="l1", make="Toyota", model="Corolla", version="", year=2018, fuel_type="Gasolina")
    monkeypatch.setattr(svc, "find_fipe_catalog_candidates", lambda *a, **k: [_entry(brand_name="Honda", model_name="Civic", model_year=2015)])
    out = svc.resolve_listing_to_fipe_candidates(None, listing=listing, reference_month="2026-05", limit=10)
    assert out["status"] == "no_match"


def test_insufficient_data():
    listing = SimpleNamespace(id="l1", make=None, model="Civic", version="", year=None, fuel_type="Gasolina")
    out = svc.resolve_listing_to_fipe_candidates(None, listing=listing, reference_month="2026-05", limit=10)
    assert out["status"] == "insufficient_data"


def test_fuel_match_vs_mismatch():
    q = {"make": "honda", "model": "civic", "version": "", "year": 2015, "fuel_type": "gasolina"}
    ok = svc.score_fipe_candidate(listing_query=q, catalog_entry=_entry(fuel="Gasolina"))
    bad = svc.score_fipe_candidate(listing_query=q, catalog_entry=_entry(fuel="Diesel"))
    assert ok["confidence_score"] > bad["confidence_score"]
    assert "combustível divergente" in bad["warnings"]
