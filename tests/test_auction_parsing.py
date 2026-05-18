from app.sources.auctions.parsing import normalize_item_type


def test_normalize_item_type_real_estate_terms():
    assert normalize_item_type("imóvel") == "real_estate"
    assert normalize_item_type("imovel") == "real_estate"


def test_normalize_item_type_heavy_terms():
    assert normalize_item_type("pá carregadeira") == "heavy"
    assert normalize_item_type("pa carregadeira") == "heavy"


def test_normalize_item_type_truck_terms():
    assert normalize_item_type("caminhão") == "truck"
    assert normalize_item_type("ônibus") == "truck"
