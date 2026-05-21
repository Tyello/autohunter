from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import settings


def _is_sqlite_url(url: str) -> bool:
    return (url or "").startswith("sqlite")


def _engine_kwargs() -> dict:
    kwargs: dict = {"pool_pre_ping": True}
    if _is_sqlite_url(settings.database_url):
        return kwargs
    kwargs.update(
        {
            "pool_size": int(settings.db_pool_size),
            "max_overflow": int(settings.db_max_overflow),
            "pool_recycle": int(settings.db_pool_recycle),
            "pool_timeout": int(settings.db_pool_timeout),
        }
    )
    if int(settings.db_connect_timeout) > 0:
        kwargs["connect_args"] = {"connect_timeout": int(settings.db_connect_timeout)}
    return kwargs


engine = create_engine(settings.database_url, **_engine_kwargs())

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
