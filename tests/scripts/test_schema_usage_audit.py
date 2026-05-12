from scripts.schema_usage_audit import ColumnInfo, classify, parse_models


def test_parse_models_finds_tables():
    tables = parse_models()
    assert tables
    assert any(t.table_name == "car_listings" for t in tables)


def test_classify_priority():
    c = ColumnInfo(name="x", read_hits=1)
    assert classify(c) == "READ_ACTIVE"
    c = ColumnInfo(name="x", write_hits=1)
    assert classify(c) == "WRITE_ONLY"
    c = ColumnInfo(name="x")
    assert classify(c) == "LEGACY_CANDIDATE"
