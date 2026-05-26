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
    assert "ano próximo (diferença de 1 ano)" in scored["warnings"]
    assert scored["confidence_score"] <= 95


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


def test_vehicle_tokens_keep_short_and_numeric():
    toks = svc.important_vehicle_tokens("Civic SI 2.4 16V")
    assert "civic" in toks and "si" in toks and "2" in toks and "4" in toks


def test_vehicle_tokens_golf_gti():
    toks = svc.important_vehicle_tokens("Golf 2.0 TSI GTI")
    assert {"golf", "2", "0", "tsi", "gti"}.issubset(toks)


def test_score_year_delta_warning_and_penalty():
    q = {"make": "honda", "model": "civic si", "version": "", "year": 2015, "fuel_type": "gasolina"}
    near = svc.score_fipe_candidate(listing_query=q, catalog_entry=_entry(model_year=2014, model_name="Civic SI"))
    far = svc.score_fipe_candidate(listing_query=q, catalog_entry=_entry(model_year=2011, model_name="Civic SI"))
    assert "ano próximo (diferença de 1 ano)" in near["warnings"]
    assert far["confidence_score"] < near["confidence_score"]


def test_resolve_high_gap_matched(monkeypatch):
    listing = SimpleNamespace(id="l1", make="Honda", model="Civic Si", version="", year=2015, fuel_type="Gasolina")
    monkeypatch.setattr(svc, "find_fipe_catalog_candidates", lambda *a, **k: [_entry(id="e1", model_name="Civic SI 2.4", model_year=2015), _entry(id="e2", model_name="City LX", model_year=2013)])
    out = svc.resolve_listing_to_fipe_candidates(None, listing=listing, reference_month="2026-05", limit=10)
    assert out["status"] == "matched"


def test_civic_si_relevant_candidate():
    q = {"make": "honda", "model": "civic si", "version": "", "year": 2015, "fuel_type": "gasolina"}
    scored = svc.score_fipe_candidate(listing_query=q, catalog_entry=_entry(model_name="Civic Sedan SI 2.4 16V", model_year=2015))
    assert scored["confidence_label"] in {"high", "medium"}
