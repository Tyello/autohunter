from types import SimpleNamespace

from app.bot.renderers import render_user_wishlists


def test_friendly_filters_with_dict_shape():
    text = render_user_wishlists([
        {"index": 1, "query": "dict", "filters": [{"field": "year", "operator": "gte", "value": "2018"}], "tracked_count": 0, "tracked_limit": 3, "is_active": True},
    ])
    assert "Ano a partir de 2018" in text


def test_friendly_filters_with_object_shape_and_invalid_ignored():
    text = render_user_wishlists([
        {"index": 1, "query": "obj", "filters": [
            SimpleNamespace(field="year", operator="gte", value="2018"),
            SimpleNamespace(field="year", operator="lte", value="2020"),
            SimpleNamespace(field="state", operator="eq", value="SP"),
            SimpleNamespace(value="invalid"),
        ], "tracked_count": 0, "tracked_limit": 3, "is_active": True},
    ])
    assert "Ano entre 2018 e 2020" in text
    assert "Estado: SP" in text
