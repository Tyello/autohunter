#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.engine.url import make_url

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pydantic import Field
from pydantic_core import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

REQUIRED_CAR_LISTING_COLUMNS = {"doors", "body_type", "cross_source_fingerprint"}
REQUIRED_NOTIFICATION_INDEX = "ix_notifications_user_sent_today"


class RuntimeSettings(BaseSettings):
    database_url: str = Field(alias="DATABASE_URL")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@dataclass
class CheckResult:
    level: str
    message: str


def classify_database_url(database_url: str) -> Tuple[str, str]:
    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError, TypeError):
        return (
            "FAIL",
            "DATABASE_URL inválida ou malformada. Verifique o formato postgresql+psycopg://...",
        )
    driver = (url.drivername or "").lower()
    if driver.startswith("sqlite"):
        return "FAIL", f"DATABASE_URL usa SQLite ({url.drivername}). Esta validação exige PostgreSQL/Supabase real."
    if driver.startswith("postgresql"):
        return "OK", f"DATABASE_URL aceita para validação PostgreSQL ({url.drivername})."
    return "FAIL", f"DATABASE_URL usa dialect não suportado ({url.drivername}). Esperado PostgreSQL."


def normalize_sql(sql: str) -> str:
    lowered = (sql or "").lower()
    compact = re.sub(r"\s+", " ", lowered)
    return compact.strip()


def has_sent_partial_condition(index_definition: str) -> bool:
    normalized = normalize_sql(index_definition)
    return bool(re.search(r"where\s+\(?\s*status\s*=\s*'sent'\s*\)?", normalized))


def evaluate_required_columns(existing_columns: Iterable[str]) -> Tuple[bool, List[str]]:
    existing = {c.lower() for c in existing_columns}
    missing = sorted(c for c in REQUIRED_CAR_LISTING_COLUMNS if c.lower() not in existing)
    return (len(missing) == 0, missing)


def summarize_results(results: Sequence[CheckResult]) -> Tuple[dict, int]:
    counts = {"OK": 0, "WARNING": 0, "FAIL": 0}
    for result in results:
        counts[result.level] += 1
    exit_code = 1 if counts["FAIL"] else 0
    return counts, exit_code


def load_alembic_heads() -> List[str]:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    return list(script.get_heads())


def run_validation(database_url: Optional[str] = None) -> Tuple[List[CheckResult], int]:
    results: List[CheckResult] = []
    url = database_url
    if not url:
        try:
            url = RuntimeSettings().database_url
        except ValidationError:
            url = None
    if not url:
        results.append(CheckResult("FAIL", "DATABASE_URL não configurada. Exemplo: DATABASE_URL=postgresql+psycopg://..."))
        counts, exit_code = summarize_results(results)
        _print_results(results, counts)
        return results, exit_code

    level, message = classify_database_url(url)
    results.append(CheckResult(level, message))
    if level == "FAIL":
        counts, exit_code = summarize_results(results)
        _print_results(results, counts)
        return results, exit_code

    try:
        engine: Engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            results.append(CheckResult("OK", "Conexão com banco estabelecida."))
            if conn.dialect.name != "postgresql":
                results.append(CheckResult("FAIL", f"Dialect conectado é {conn.dialect.name}, esperado postgresql."))
                counts, code = summarize_results(results)
                _print_results(results, counts)
                return results, code
            results.append(CheckResult("OK", "Dialect conectado confirmado: postgresql."))

            heads = load_alembic_heads()
            if len(heads) != 1:
                results.append(CheckResult("FAIL", f"Alembic no código possui {len(heads)} heads (esperado: 1). Heads: {heads}"))
            else:
                results.append(CheckResult("OK", f"Alembic no código possui head único: {heads[0]}"))

            try:
                db_revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            except SQLAlchemyError:
                db_revision = None
                results.append(CheckResult("FAIL", "Tabela alembic_version ausente ou inacessível no banco."))

            if db_revision:
                results.append(CheckResult("OK", f"Revision atual do banco: {db_revision}"))
                if len(heads) == 1 and db_revision == heads[0]:
                    results.append(CheckResult("OK", "Revision do banco está no head esperado."))
                else:
                    results.append(CheckResult("FAIL", "Revision do banco não corresponde ao head esperado do código."))

            inspector = inspect(conn)
            car_columns = [col["name"] for col in inspector.get_columns("car_listings")]
            columns_ok, missing = evaluate_required_columns(car_columns)
            if columns_ok:
                results.append(CheckResult("OK", "car_listings contém colunas críticas: doors, body_type, cross_source_fingerprint."))
            else:
                results.append(CheckResult("FAIL", f"car_listings sem colunas críticas: {', '.join(missing)}"))

            index_rows = conn.execute(
                text(
                    """
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = ANY(current_schemas(false))
                      AND tablename = 'notifications'
                      AND indexname = :index_name
                    """
                ),
                {"index_name": REQUIRED_NOTIFICATION_INDEX},
            ).fetchall()

            if not index_rows:
                results.append(CheckResult("FAIL", f"Índice {REQUIRED_NOTIFICATION_INDEX} não encontrado em notifications."))
            else:
                indexdef = index_rows[0].indexdef
                if has_sent_partial_condition(indexdef):
                    results.append(CheckResult("OK", f"Índice {REQUIRED_NOTIFICATION_INDEX} é partial com WHERE status = 'sent'."))
                else:
                    results.append(CheckResult("FAIL", f"Índice {REQUIRED_NOTIFICATION_INDEX} existe, mas não contém WHERE status = 'sent'."))

    except SQLAlchemyError as exc:
        results.append(CheckResult("FAIL", f"Falha de conexão/consulta no banco: {exc}"))

    counts, exit_code = summarize_results(results)
    _print_results(results, counts)
    return results, exit_code


def _print_results(results: Sequence[CheckResult], counts: dict) -> None:
    print("PostgreSQL schema validation")
    print("=" * 40)
    for result in results:
        print(f"{result.level}: {result.message}")
    print("-" * 40)
    print(f"Resumo -> OK: {counts['OK']} | WARNING: {counts['WARNING']} | FAIL: {counts['FAIL']}")


def main() -> int:
    _, exit_code = run_validation()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
