from datetime import datetime, timedelta, timezone

from sqlalchemy import event

from app.models.source_run import SourceRun
from app.services import autopilot_service


def _run(db, source, status, created_at):
    db.add(
        SourceRun(
            source=source,
            kind="scheduler",
            status=status,
            url=f"https://{source}.example/lista",
            created_at=created_at,
        )
    )


def _seed(db, now):
    def m(minutes):
        return now - timedelta(minutes=minutes)

    # mercadolivre: janela 4/5 bloqueados; baseline 0/20 bloqueados => candidato
    for i, status in enumerate(["blocked"] * 4 + ["success"]):
        _run(db, "mercadolivre", status, m(i + 1))
    for i in range(20):
        _run(db, "mercadolivre", "success", m(60 + i))
    # mercadolivre: bloqueado exatamente em `now` fica fora da janela [start, end)
    _run(db, "mercadolivre", "blocked", now)

    # kabum: janela 5/5 bloqueados, sem baseline => candidato;
    # 50 bloqueados há 8 dias ficam fora do baseline [b_start, b_end)
    for i in range(5):
        _run(db, "kabum", "blocked", m(i + 1))
    for i in range(50):
        _run(db, "kabum", "blocked", m(8 * 24 * 60 + i))

    # olx: janela 3/5 (0.60); baseline 4/12 (0.33 => limiar 0.767) => não é candidato
    for i, status in enumerate(["blocked"] * 3 + ["success"] * 2):
        _run(db, "olx", status, m(i + 1))
    for i in range(12):
        _run(db, "olx", "blocked" if i < 4 else "success", m(120 + i))

    # carro: janela 4/5 (0.80); baseline 9/10 (0.90 => limiar 1.9) => não é candidato
    for i, status in enumerate(["blocked"] * 4 + ["success"]):
        _run(db, "carro", status, m(i + 1))
    for i in range(10):
        _run(db, "carro", "blocked" if i < 9 else "success", m(120 + i))

    # zap: total na janela = 4 (<5) => não é candidato, mesmo 100% bloqueado
    for i in range(4):
        _run(db, "zap", "blocked", m(i + 1))


def test_blocked_spike_candidates_match_expected_scenarios(db, monkeypatch):
    monkeypatch.setattr(autopilot_service.settings, "autopilot_window_minutes", 30)
    now = datetime.now(timezone.utc)
    _seed(db, now)
    db.commit()

    cands = autopilot_service._candidate_blocked_spike(db, now)
    by_source = {c.source: c for c in cands}

    assert set(by_source) == {"mercadolivre", "kabum"}

    ml = by_source["mercadolivre"].evidence
    assert ml["total"] == 5
    assert ml["blocked"] == 4
    assert ml["baseline"]["total"] == 20
    assert ml["baseline"]["blocked"] == 0

    kb = by_source["kabum"].evidence
    assert kb["total"] == 5
    assert kb["blocked"] == 5
    assert kb["baseline"]["total"] == 0
    assert kb["baseline"]["blocked"] == 0


def test_candidate_blocked_spike_uses_single_aggregate_query(db, monkeypatch):
    monkeypatch.setattr(autopilot_service.settings, "autopilot_window_minutes", 30)
    now = datetime.now(timezone.utc)
    _seed(db, now)
    db.commit()

    engine = db.get_bind()
    statements = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        autopilot_service._candidate_blocked_spike(db, now)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    # Exclui a query de samples (SELECT ... LIMIT, sem GROUP BY) e o contexto por source.
    aggregates = [
        s for s in statements
        if "source_runs" in s.lower() and "group by" in s.lower()
    ]
    assert len(aggregates) == 1, aggregates


def test_blocked_spike_window_boundaries_are_half_open(db, monkeypatch):
    monkeypatch.setattr(autopilot_service.settings, "autopilot_window_minutes", 30)
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    start = now - timedelta(minutes=30)
    b_start = start - timedelta(days=7)

    def m(minutes):
        return now - timedelta(minutes=minutes)

    # edge_start: run em `start` entra na janela [start, now) e fica fora do baseline [b_start, start)
    for minutes in (1, 2, 3, 4):
        _run(db, "edge_start", "blocked", m(minutes))
    _run(db, "edge_start", "blocked", start)

    # edge_end: run em `now` fica fora da janela (end exclusivo)
    for minutes in (1, 2, 3, 4, 5):
        _run(db, "edge_end", "blocked", m(minutes))
    _run(db, "edge_end", "blocked", now)

    # edge_bstart: 3 runs em b_start entram no baseline; 2 runs 1s antes ficam fora
    for minutes in (1, 2, 3, 4, 5):
        _run(db, "edge_bstart", "blocked", m(minutes))
    for _ in range(3):
        _run(db, "edge_bstart", "success", b_start)
    for _ in range(2):
        _run(db, "edge_bstart", "success", b_start - timedelta(seconds=1))

    # just_before_start: 1 run 1s antes de start cai no baseline, não na janela
    for minutes in (1, 2, 3, 4, 5):
        _run(db, "just_before_start", "blocked", m(minutes))
    _run(db, "just_before_start", "success", start - timedelta(seconds=1))
    db.commit()

    cands = autopilot_service._candidate_blocked_spike(db, now)
    by_source = {c.source: c for c in cands}

    assert set(by_source) == {"edge_start", "edge_end", "edge_bstart", "just_before_start"}

    es = by_source["edge_start"].evidence
    assert es["total"] == 5
    assert es["baseline"]["total"] == 0

    ee = by_source["edge_end"].evidence
    assert ee["total"] == 5

    eb = by_source["edge_bstart"].evidence
    assert eb["baseline"]["total"] == 3

    jb = by_source["just_before_start"].evidence
    assert jb["total"] == 5
    assert jb["baseline"]["total"] == 1
