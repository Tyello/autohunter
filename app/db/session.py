import threading
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

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


class ThreadSafeSession(Session):
    """Subclass de SQLAlchemy Session com proteção contra acesso de threads não-donos."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._owner_thread_id = threading.current_thread().ident

    def _check_thread_access(self):
        """Verifica se a thread atual é a dona desta sessão."""
        current_id = threading.current_thread().ident
        if current_id != self._owner_thread_id:
            raise RuntimeError(
                f"Acesso de thread cruzada detectado: sessão criada em thread {self._owner_thread_id}, "
                f"acessada em thread {current_id}"
            )

    def execute(self, *args, **kwargs):
        self._check_thread_access()
        return super().execute(*args, **kwargs)

    def query(self, *args, **kwargs):
        self._check_thread_access()
        return super().query(*args, **kwargs)

    def add(self, instance, *args, **kwargs):
        self._check_thread_access()
        return super().add(instance, *args, **kwargs)

    def commit(self):
        self._check_thread_access()
        return super().commit()

    def rollback(self):
        self._check_thread_access()
        return super().rollback()

    def close(self):
        self._check_thread_access()
        return super().close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=ThreadSafeSession)

# Sessionmaker sem guarda de thread, reservado para a camada HTTP (app/db/deps.py).
# O FastAPI/Starlette executa dependências síncronas via run_in_threadpool, podendo
# despachar a criação da Session e o uso subsequente em threads diferentes do pool
# (sempre sequencialmente, nunca concorrente) — isso não é o cenário de compartilhamento
# indevido entre threads que o guard de ThreadSafeSession existe para detectar.
SessionLocalHTTP = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def session_scope():
    """Context manager que provê uma nova sessão thread-safe para cada bloco.

    Exemplos:
        with session_scope() as db:
            user = db.query(User).filter_by(id=1).first()
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
