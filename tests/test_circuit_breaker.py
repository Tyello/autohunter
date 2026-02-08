"""
Testes para Circuit Breaker.
"""

import time
import pytest
from app.scrapers.shared.circuit_breaker import CircuitBreaker, get_circuit_breaker


def test_circuit_breaker_starts_closed():
    """Circuit breaker deve iniciar no estado CLOSED."""
    cb = CircuitBreaker("test_source", failure_threshold=3)
    
    assert cb.get_state() == "closed"
    assert cb.is_open() is False


def test_circuit_breaker_opens_after_threshold():
    """Circuit breaker deve abrir após N falhas consecutivas."""
    cb = CircuitBreaker("test_source", failure_threshold=3)
    
    # 2 falhas - ainda fechado
    cb.record_failure()
    cb.record_failure()
    assert cb.get_state() == "closed"
    assert cb.is_open() is False
    
    # 3ª falha - abre
    cb.record_failure()
    assert cb.get_state() == "open"
    assert cb.is_open() is True


def test_circuit_breaker_success_resets_failures():
    """Sucesso deve resetar contador de falhas."""
    cb = CircuitBreaker("test_source", failure_threshold=3)
    
    cb.record_failure()
    cb.record_failure()
    cb.record_success()  # reset
    
    # Ainda precisa de 3 falhas para abrir
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open() is False
    
    cb.record_failure()
    assert cb.is_open() is True


def test_circuit_breaker_transitions_to_half_open():
    """Circuit breaker deve ir para HALF_OPEN após cooldown."""
    cb = CircuitBreaker("test_source", failure_threshold=2, base_cooldown_s=1)
    
    # Abre
    cb.record_failure()
    cb.record_failure()
    assert cb.get_state() == "open"
    
    # Aguarda cooldown
    time.sleep(1.1)
    
    # Deve estar half_open agora
    assert cb.is_open() is False  # permite tentativa
    assert cb.get_state() == "half_open"


def test_circuit_breaker_half_open_success_closes():
    """Sucesso em HALF_OPEN deve voltar para CLOSED."""
    cb = CircuitBreaker("test_source", failure_threshold=2, base_cooldown_s=1)
    
    # Abre
    cb.record_failure()
    cb.record_failure()
    
    # Aguarda half_open
    time.sleep(1.1)
    cb.is_open()  # trigger transition
    
    # Sucesso -> fecha
    cb.record_success()
    assert cb.get_state() == "closed"
    assert cb.is_open() is False


def test_circuit_breaker_half_open_failure_reopens():
    """Falha em HALF_OPEN deve voltar para OPEN."""
    cb = CircuitBreaker("test_source", failure_threshold=2, base_cooldown_s=1)
    
    # Abre
    cb.record_failure()
    cb.record_failure()
    
    # Aguarda half_open
    time.sleep(1.1)
    cb.is_open()
    
    # Falha -> volta para open
    cb.record_failure()
    assert cb.get_state() == "open"
    assert cb.is_open() is True


def test_circuit_breaker_exponential_backoff():
    """Cooldown deve crescer exponencialmente."""
    cb = CircuitBreaker("test_source", failure_threshold=2, base_cooldown_s=10, max_cooldown_s=100)
    
    # Primeira abertura: cooldown = 10s
    cb.record_failure()
    cb.record_failure()
    stats = cb.get_stats()
    # failures=2, threshold=2 -> opens=0 -> cooldown = 10 * 2^0 = 10
    
    # Simula mais falhas (sem aguardar cooldown)
    cb._state.failures = 5  # Simula mais aberturas
    cooldown = cb._calculate_cooldown()
    # opens = 5 - 2 = 3 -> cooldown = 10 * 2^3 = 80
    assert cooldown == 80


def test_get_circuit_breaker_singleton():
    """get_circuit_breaker deve retornar mesmo objeto para mesma fonte."""
    cb1 = get_circuit_breaker("test_source")
    cb2 = get_circuit_breaker("test_source")
    
    assert cb1 is cb2


def test_circuit_breaker_stats():
    """Deve retornar estatísticas corretas."""
    cb = CircuitBreaker("test_source", failure_threshold=3)
    
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    
    stats = cb.get_stats()
    
    assert stats["source"] == "test_source"
    assert stats["state"] == "closed"
    assert stats["failures"] == 0  # resetado pelo sucesso
    assert stats["successes"] == 1


def test_circuit_breaker_reset():
    """Reset deve voltar ao estado inicial."""
    cb = CircuitBreaker("test_source", failure_threshold=2)
    
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open() is True
    
    cb.reset()
    
    assert cb.is_open() is False
    assert cb.get_state() == "closed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
