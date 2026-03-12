from app.scrapers.parse_failure import decide_parse_failure


def test_parse_failure_when_raw_exists_but_no_normalized_output():
    d = decide_parse_failure(
        source="olx",
        url="https://example/search",
        found=0,
        adapter_meta={"raw_count": 8, "normalized_count": 0, "partial_failure": False},
    )
    assert d is not None
    assert d.code == "raw_without_normalized"


def test_legit_empty_when_no_raw_items():
    d = decide_parse_failure(
        source="olx",
        url="https://example/search",
        found=0,
        adapter_meta={"raw_count": 0, "normalized_count": 0, "partial_failure": False},
    )
    assert d is None
