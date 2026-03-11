from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "source_regression"


def load_fixture(source: str, scenario: str, name: str) -> str:
    return (FIXTURE_ROOT / source / scenario / name).read_text(encoding="utf-8")


def load_expectations(source: str, scenario: str) -> Dict[str, Any]:
    return json.loads(load_fixture(source, scenario, "expectations.json"))


def index_by_external_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(it.get("external_id") or ""): it for it in items if it.get("external_id")}


def assert_core_fields(item: dict[str, Any], must_have: list[str]) -> None:
    field_map = {
        "source_listing_id": item.get("external_id") or item.get("source_listing_id"),
        "km": item.get("mileage_km") or item.get("km"),
        "thumbnail_url": item.get("thumbnail_url") or item.get("image_url"),
    }
    for field in must_have:
        value = field_map.get(field, item.get(field))
        assert value not in (None, ""), f"campo obrigatório ausente: {field}"


def assert_optional_absent(item: dict[str, Any], optional_absent: list[str]) -> None:
    field_map = {
        "km": item.get("mileage_km") or item.get("km"),
        "year": item.get("year"),
    }
    for field in optional_absent:
        assert field_map.get(field) in (None, ""), f"campo opcional deveria estar ausente: {field}"
