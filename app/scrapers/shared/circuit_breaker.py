"""
Circuit Breaker - Previne thrashing quando fonte está consistentemente bloqueada.

Implementa padrão Circuit Breaker com 3 estados:
- CLOSED: Normal operation
- OPEN: Bloqueado após N falhas consecutivas
- HALF_OPEN: Testando se fonte voltou a funcionar
"""

from __future__ import annotations
import time
import threading
from dataclasses import dataclass
from typing import Dict


@dataclass
class CircuitState:
    """Estado interno do circuit breaker."""
    
    failures: int = 0
    successes: int = 0
    last_failure_ts: float = 0
    last_success_ts: float = 0
    opened_at: float = 0
    state: str = "closed"  # closed | open | half_open


class CircuitBreaker:
    """Circuit breaker por source.
    
    Previne tentativas inúteis quando uma fonte está consistentemente
    bloqueada ou falhando.
    
    Estados:
    - CLOSED: Operação normal
    - OPEN: Bloqueado após N falhas consecutivas, aguarda cooldown
    - HALF_OPEN: Cooldown passou, permite 1 tentativa para testar
    
    Comportamento:
    - Após `failure_threshold` falhas consecutivas → OPEN
    - Permanece OPEN por cooldown (exponencial backoff)
    - Após cooldown → HALF_OPEN (permite 1 tentativa)
    - Se tentativa HALF_OPEN sucede → CLOSED
    - Se tentativa HALF_OPEN falha → OPEN novamente (cooldown maior)
    
    Example:
        cb = CircuitBreaker("olx", failure_threshold=5, base_cooldown_s=60)
        
        if cb.is_open():
            print("Skipping scrape - circuit breaker is open")
            return
        
        try:
            result = scrape()
            cb.record_success()
        except Exception:
            cb.record_failure()
    """
    
    def __init__(
        self,
        source: str,
        failure_threshold: int = 5,
        base_cooldown_s: int = 60,
        max_cooldown_s: int = 3600
    ):
        """Inicializa circuit breaker.
        
        Args:
            source: Nome da fonte
            failure_threshold: Número de falhas consecutivas para abrir
            base_cooldown_s: Tempo base de cooldown (segundos)
            max_cooldown_s: Tempo máximo de cooldown (segundos)
        """
        self.source = source
        self.failure_threshold = failure_threshold
        self.base_cooldown_s = base_cooldown_s
        self.max_cooldown_s = max_cooldown_s
        
        self._state = CircuitState()
        self._lock = threading.Lock()
    
    def is_open(self) -> bool:
        """Verifica se circuit breaker está aberto (bloqueando requests).
        
        Returns:
            True se aberto (deve pular request), False se pode tentar
        """
        with self._lock:
            if self._state.state == "closed":
                return False
            
            if self._state.state == "open":
                # Verifica se passou o cooldown
                elapsed = time.time() - self._state.opened_at
                cooldown = self._calculate_cooldown()
                
                if elapsed >= cooldown:
                    # Cooldown passou - transição para half_open
                    self._state.state = "half_open"
                    return False
                
                # Ainda em cooldown
                return True
            
            # half_open: permite 1 tentativa
            return False
    
    def record_success(self):
        """Registra sucesso (fonte funcionou).
        
        - CLOSED: reset contador de falhas
        - HALF_OPEN: volta para CLOSED
        """
        with self._lock:
            self._state.successes += 1
            self._state.last_success_ts = time.time()
            
            if self._state.state == "half_open":
                # Tentativa half_open sucedeu - volta para closed
                self._state.state = "closed"
                self._state.failures = 0
                self._state.opened_at = 0
            
            elif self._state.state == "closed":
                # Reset contador de falhas
                self._state.failures = 0
    
    def record_failure(self):
        """Registra falha (fonte bloqueada/erro).
        
        - CLOSED: incrementa contador, abre se atingir threshold
        - HALF_OPEN: volta para OPEN (com cooldown maior)
        """
        with self._lock:
            self._state.failures += 1
            self._state.last_failure_ts = time.time()
            
            if self._state.state == "half_open":
                # Tentativa half_open falhou - volta para open
                self._state.state = "open"
                self._state.opened_at = time.time()
            
            elif self._state.state == "closed":
                # Verifica se deve abrir
                if self._state.failures >= self.failure_threshold:
                    self._state.state = "open"
                    self._state.opened_at = time.time()
    
    def get_state(self) -> str:
        """Retorna estado atual (closed|open|half_open)."""
        with self._lock:
            return self._state.state
    
    def get_stats(self) -> dict:
        """Retorna estatísticas do circuit breaker."""
        with self._lock:
            return {
                "source": self.source,
                "state": self._state.state,
                "failures": self._state.failures,
                "successes": self._state.successes,
                "last_failure_ts": self._state.last_failure_ts,
                "last_success_ts": self._state.last_success_ts,
                "opened_at": self._state.opened_at,
                "cooldown_remaining_s": self._get_cooldown_remaining(),
            }
    
    def reset(self):
        """Reset manual do circuit breaker (para testes/admin)."""
        with self._lock:
            self._state = CircuitState()
    
    def _calculate_cooldown(self) -> int:
        """Calcula cooldown atual (exponential backoff)."""
        # Cooldown cresce exponencialmente com número de aberturas
        # failures - threshold = número de vezes que abriu
        opens = max(0, self._state.failures - self.failure_threshold)
        cooldown = self.base_cooldown_s * (2 ** opens)
        return min(cooldown, self.max_cooldown_s)
    
    def _get_cooldown_remaining(self) -> int:
        """Tempo restante de cooldown (segundos)."""
        if self._state.state != "open":
            return 0
        
        elapsed = time.time() - self._state.opened_at
        cooldown = self._calculate_cooldown()
        remaining = max(0, cooldown - elapsed)
        
        return int(remaining)


# Registry global de circuit breakers
_circuit_breakers: Dict[str, CircuitBreaker] = {}
_cb_lock = threading.Lock()


def get_circuit_breaker(source: str, **kwargs) -> CircuitBreaker:
    """Obtém circuit breaker para uma fonte (singleton por fonte).
    
    Args:
        source: Nome da fonte
        **kwargs: Parâmetros para CircuitBreaker (se criar novo)
    
    Returns:
        CircuitBreaker para a fonte
    """
    with _cb_lock:
        if source not in _circuit_breakers:
            _circuit_breakers[source] = CircuitBreaker(source, **kwargs)
        return _circuit_breakers[source]


def get_all_circuit_breakers() -> Dict[str, CircuitBreaker]:
    """Retorna todos os circuit breakers (para admin/monitoring)."""
    with _cb_lock:
        return dict(_circuit_breakers)


def reset_circuit_breaker(source: str):
    """Reset manual de um circuit breaker."""
    cb = get_circuit_breaker(source)
    cb.reset()


def reset_all_circuit_breakers():
    """Reset de todos os circuit breakers."""
    with _cb_lock:
        for cb in _circuit_breakers.values():
            cb.reset()
