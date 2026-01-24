import pytest

from app.core.query_match import build_preset_rule, is_match


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Honda Civic SI 2008 Manual VTEC", True),
        ("Honda Civic 2015 2.0 LXR 16V", False),
        ("Honda Civic Type-R 2024 turbo", False),
        ("Civic SiR 1999 vtec", True),
    ],
)
def test_civic_si(title, expected):
    rule = build_preset_rule("civic si")
    assert is_match(title, rule) is expected


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Honda Civic Hatch 1994", True),
        ("Honda Civic Hatchback 1997", True),
        ("Honda Civic Sedan 1997", False),
        ("Honda Civic Type R 2020", False),
    ],
)
def test_civic_hatch(title, expected):
    rule = build_preset_rule("civic hatch")
    assert is_match(title, rule) is expected
