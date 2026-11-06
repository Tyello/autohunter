"""D5/REQ-006: polling adaptativo para workers ociosos.

Cobre:
- função pura `_next_wait` (cálculo do intervalo);
- `start_worker_thread` com `max_idle_seconds` (espera sequencial, sem tempo real);
- retornos de `job_http_queue_worker` e `job_browser_queue_worker` (False = fila vazia, True = job).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

from app.core.settings import settings
from app.scheduler import worker_threads as wt
from app.scheduler import http_queue_job as hj
from app.scheduler import browser_queue_job as bqj


# ---------------------------------------------------------------------------
# _next_wait (função pura)
# ---------------------------------------------------------------------------

def test_next_wait_streak_zero_returns_base_interval():
    assert wt._next_wait(2, 0, 10) == 2


def test_next_wait_without_cap_ignores_streak():
    # Sem max_idle_seconds o comportamento deve ser idêntico ao atual.
    assert wt._next_wait(2, 0, None) == 2
    assert wt._next_wait(2, 3, None) == 2
    assert wt._next_wait(5, 10, None) == 5


def test_next_wait_doubles_per_idle_streak_until_cap():
    assert wt._next_wait(2, 1, 10) == 4
    assert wt._next_wait(2, 2, 10) == 8
    assert wt._next_wait(2, 3, 10) == 10  # 16 limitado ao teto
    assert wt._next_wait(2, 4, 10) == 10
    assert wt._next_wait(2, 50, 10) == 10


def test_next_wait_huge_streak_is_bounded_and_fast():
    # Ociosidade de dias: o streak chega a centenas de milhares; deve continuar no teto.
    assert wt._next_wait(2, 10_000_000, 10) == 10
    assert wt._next_wait(2, 10_000_000, 3600) == 3600


def test_next_wait_never_drops_below_base_when_cap_is_smaller():
    # Base configurado acima do teto: ocioso não pode ficar mais rápido que o normal.
    assert wt._next_wait(30, 1, 10) == 30
    assert wt._next_wait(30, 5, 10) == 30


# ---------------------------------------------------------------------------
# start_worker_thread com max_idle_seconds
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_shutdown(monkeypatch: pytest.MonkeyPatch):
    """Substitui espera real por registro de intervalos.

    `wait()` registra o timeout e devolve False (sem bloquear). O shutdown é
    sinalizado quando `max_waits` esperas foram registradas.
    """
    state = {"waits": [], "max_waits": 0}

    class _FakeEvent:
        def wait(self, timeout=None):
            state["waits"].append(timeout)
            return False

    monkeypatch.setattr(wt, "_shutdown_event", _FakeEvent())
    monkeypatch.setattr(
        wt,
        "is_shutdown_requested",
        lambda: len(state["waits"]) >= state["max_waits"],
    )
    monkeypatch.setattr(wt, "WORKER_THREADS", [])
    return state


def _run_sequence(fake_shutdown, outcomes, *, seconds, max_idle_seconds):
    """Executa worker com uma sequência de resultados de fn().

    Cada item de `outcomes` é um valor a retornar ou uma exceção a lançar.
    """
    fake_shutdown["max_waits"] = len(outcomes)
    it = iter(outcomes)

    def fn():
        item = next(it)
        if isinstance(item, BaseException):
            raise item
        return item

    kwargs = {"seconds": seconds, "name": "test_adaptive"}
    if max_idle_seconds is not None:
        kwargs["max_idle_seconds"] = max_idle_seconds
    thread = wt.start_worker_thread(fn, **kwargs)
    thread.join(timeout=5)
    assert not thread.is_alive()
    return fake_shutdown["waits"]


def test_worker_idle_streak_grows_then_caps_then_resets_on_true(fake_shutdown):
    waits = _run_sequence(
        fake_shutdown,
        [False, False, False, True, False, None],
        seconds=2,
        max_idle_seconds=10,
    )
    # ocioso 1→4, ocioso 2→8, ocioso 3→min(16,10)=10, True→2, ocioso 1→4, None→2
    assert waits == [4, 8, 10, 2, 4, 2]


def test_worker_exception_resets_idle_streak(fake_shutdown):
    waits = _run_sequence(
        fake_shutdown,
        [False, RuntimeError("boom"), False],
        seconds=2,
        max_idle_seconds=10,
    )
    assert waits == [4, 2, 4]


def test_worker_without_cap_keeps_base_interval_even_when_idle(fake_shutdown):
    waits = _run_sequence(
        fake_shutdown,
        [False, False, False],
        seconds=2,
        max_idle_seconds=None,
    )
    assert waits == [2, 2, 2]


def test_worker_only_exact_false_counts_as_idle(fake_shutdown):
    # 0 e "" são falsy mas não são False: devem manter intervalo base.
    waits = _run_sequence(
        fake_shutdown,
        [0, "", None],
        seconds=2,
        max_idle_seconds=10,
    )
    assert waits == [2, 2, 2]


# ---------------------------------------------------------------------------
# Workers: retorno False com fila vazia, True com job
# ---------------------------------------------------------------------------

class _FakeDB:
    def commit(self):
        pass

    def rollback(self):
        pass

    def get(self, *_args, **_kwargs):
        return None


@contextmanager
def _fake_session_scope():
    yield _FakeDB()


class _FakeJob:
    def __init__(self, source="olx", priority=0):
        self.id = uuid.uuid4()
        self.source = source
        self.priority = priority


@pytest.fixture
def no_side_effects(monkeypatch: pytest.MonkeyPatch):
    """Neutraliza logs, marcação de status e sessão real nos dois workers."""
    for mod in (hj, bqj):
        monkeypatch.setattr(mod, "session_scope", _fake_session_scope)
        monkeypatch.setattr(mod, "is_shutdown_requested", lambda: False)
        monkeypatch.setattr(mod, "log", lambda *a, **k: None)
        monkeypatch.setattr(mod, "mark_done", lambda *a, **k: None)
        monkeypatch.setattr(mod, "mark_failed", lambda *a, **k: None)
    monkeypatch.setattr(hj, "run_reason_for_job_priority", lambda p: None)
    monkeypatch.setattr(bqj, "run_reason_for_job_priority", lambda p: None)
    monkeypatch.setattr(settings, "enable_playwright", True)
    monkeypatch.setattr(bqj, "_log_best_effort_with_scope", lambda *a, **k: None)


def test_http_worker_returns_false_when_queue_empty(monkeypatch, no_side_effects):
    monkeypatch.setattr(hj, "dequeue_next_job", lambda *a, **k: None)
    assert hj.job_http_queue_worker() is False


def test_http_worker_returns_true_after_processing_job(monkeypatch, no_side_effects):
    monkeypatch.setattr(hj, "dequeue_next_job", lambda *a, **k: _FakeJob())
    monkeypatch.setattr(
        hj, "run_source_for_all_wishlists", lambda *a, **k: {"ok": True, "status": "ok"}
    )
    assert hj.job_http_queue_worker() is True


def test_http_worker_returns_true_when_job_raises(monkeypatch, no_side_effects):
    monkeypatch.setattr(hj, "dequeue_next_job", lambda *a, **k: _FakeJob())

    def _boom(*_a, **_k):
        raise RuntimeError("scrape exploded")

    monkeypatch.setattr(hj, "run_source_for_all_wishlists", _boom)
    assert hj.job_http_queue_worker() is True


def test_browser_worker_returns_false_when_queue_empty(monkeypatch, no_side_effects):
    monkeypatch.setattr(bqj, "dequeue_next_job", lambda *a, **k: None)
    assert bqj.job_browser_queue_worker() is False


def test_browser_worker_returns_true_after_processing_job(monkeypatch, no_side_effects):
    monkeypatch.setattr(bqj, "dequeue_next_job", lambda *a, **k: _FakeJob())
    monkeypatch.setattr(
        bqj, "run_source_for_all_wishlists", lambda *a, **k: {"ok": True, "status": "ok"}
    )
    assert bqj.job_browser_queue_worker() is True


def test_browser_worker_returns_true_when_job_raises(monkeypatch, no_side_effects):
    monkeypatch.setattr(bqj, "dequeue_next_job", lambda *a, **k: _FakeJob())

    def _boom(*_a, **_k):
        raise RuntimeError("scrape exploded")

    monkeypatch.setattr(bqj, "run_source_for_all_wishlists", _boom)
    assert bqj.job_browser_queue_worker() is True
