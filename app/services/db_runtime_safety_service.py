from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.settings import settings


POSTGRES_SUPERUSER_ROLE = "postgres"
LEAST_PRIVILEGE_RUNTIME_ROLE = "autohunter_app"
POSTGRES_ROLE_WARNING = (
    "runtime usando role postgres; recomendado usar role autohunter_app least-privilege"
)
ROLE_UNKNOWN_WARNING = (
    "não foi possível detectar role runtime do banco; valide manualmente que DATABASE_URL não usa postgres"
)


@dataclass(frozen=True)
class DatabaseRuntimeRoleCheck:
    status: str
    role: str | None
    source: str
    warning: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def detect_database_url_username(database_url: str | None = None) -> str | None:
    raw = database_url if database_url is not None else settings.database_url
    if not raw:
        return None
    try:
        url = make_url(raw)
        return url.username
    except Exception:
        try:
            parsed = urlsplit(raw)
        except Exception:
            return None
        if not parsed.username:
            return None
        return unquote(parsed.username)


def check_database_runtime_role(db: Session) -> DatabaseRuntimeRoleCheck:
    """Best-effort warning if runtime is connected as the PostgreSQL superuser.

    SQLite/test databases do not expose PostgreSQL roles, so the URL username is used
    as a conservative fallback. The check intentionally does not mutate DB state.
    """
    try:
        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else "unknown"
    except Exception:
        dialect_name = "unknown"

    if dialect_name == "postgresql":
        try:
            role = db.execute(text("select current_user")).scalar_one_or_none()
        except SQLAlchemyError as exc:
            return DatabaseRuntimeRoleCheck(
                status="warning",
                role=None,
                source="current_user",
                warning=ROLE_UNKNOWN_WARNING,
                error=str(exc)[:240],
            )
        role_s = str(role) if role is not None else None
        if role_s == POSTGRES_SUPERUSER_ROLE:
            return DatabaseRuntimeRoleCheck(
                status="warning",
                role=role_s,
                source="current_user",
                warning=POSTGRES_ROLE_WARNING,
            )
        return DatabaseRuntimeRoleCheck(status="ok", role=role_s, source="current_user")

    role = detect_database_url_username()
    if role == POSTGRES_SUPERUSER_ROLE:
        return DatabaseRuntimeRoleCheck(
            status="warning",
            role=role,
            source="DATABASE_URL",
            warning=POSTGRES_ROLE_WARNING,
        )
    if role is None:
        return DatabaseRuntimeRoleCheck(
            status="warning",
            role=None,
            source="DATABASE_URL",
            warning=ROLE_UNKNOWN_WARNING,
        )
    return DatabaseRuntimeRoleCheck(status="ok", role=role, source="DATABASE_URL")
