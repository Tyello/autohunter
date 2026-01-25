from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from fastapi.testclient import TestClient


SNAPSHOT_PATH = Path(__file__).parent / "contracts" / "openapi_snapshot.json"


def _deep_sort(obj: Any) -> Any:
    """Recursively sort dict keys for stable snapshots."""
    if isinstance(obj, dict):
        return {k: _deep_sort(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, list):
        return [_deep_sort(x) for x in obj]
    return obj


def _normalize_openapi(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only contract-relevant parts to reduce noise.

    Why:
    - `info.version` tends to change without being a breaking contract change
    - FastAPI/Starlette can add extra fields over time that are not important
      for consumers of our API.
    """

    paths = spec.get("paths", {})
    keep_paths = {
        "/health": paths.get("/health"),
        "/db-check": paths.get("/db-check"),
        "/listings": paths.get("/listings"),
        "/admin/health": paths.get("/admin/health"),
    }

    schemas = ((spec.get("components") or {}).get("schemas") or {})
    keep_schemas = {
        # our main output contract
        "CarListingOut": schemas.get("CarListingOut"),
        # FastAPI standard validation models
        "HTTPValidationError": schemas.get("HTTPValidationError"),
        "ValidationError": schemas.get("ValidationError"),
    }

    normalized = {
        "openapi": spec.get("openapi"),
        "info": {
            "title": (spec.get("info") or {}).get("title"),
        },
        "paths": keep_paths,
        "components": {"schemas": keep_schemas},
    }
    return _deep_sort(normalized)


def test_openapi_contract_snapshot():
    """Guarda contra breaking changes na API.

    Para atualizar o snapshot intencionalmente:

        UPDATE_CONTRACT=1 pytest -k openapi_contract_snapshot
    """

    from app.main import app  # imported after conftest env is set

    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    normalized = _normalize_openapi(spec)

    # Ensure directory exists
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if os.environ.get("UPDATE_CONTRACT") in {"1", "true", "yes"}:
        SNAPSHOT_PATH.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return

    if not SNAPSHOT_PATH.exists():
        raise AssertionError(
            f"OpenAPI contract snapshot missing at {SNAPSHOT_PATH}. "
            "Run UPDATE_CONTRACT=1 pytest -k openapi_contract_snapshot to generate it."
        )

    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert normalized == expected
