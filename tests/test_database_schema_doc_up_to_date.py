import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_db_schema_doc", ROOT / "scripts" / "generate_db_schema_doc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_database_schema_doc_matches_models():
    gen = _load_generator()
    existing = gen.DOC_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert existing == gen.render(existing), (
        "docs/DATABASE_SCHEMA.md desatualizado em relacao aos models. "
        "Rode: python scripts/generate_db_schema_doc.py"
    )
