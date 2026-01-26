from __future__ import annotations


def test_lifespan_does_not_start_scheduler_by_default(client):
    """Em testes/CI o scheduler deve ficar desligado (evita threads e flakiness)."""
    # O TestClient ativa o lifespan automaticamente
    assert not hasattr(client.app.state, "scheduler")
