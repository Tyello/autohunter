"""
Shared scrapers infrastructure.
"""

from app.scrapers.shared.circuit_breaker import (
    CircuitBreaker,
    get_circuit_breaker,
    get_all_circuit_breakers,
    reset_circuit_breaker,
    reset_all_circuit_breakers,
)

from app.scrapers.shared.browser_manager import (
    BrowserManager,
    get_browser_manager,
    shutdown_browser_manager,
    BrowserFetchResult,
)

__all__ = [
    "CircuitBreaker",
    "get_circuit_breaker",
    "get_all_circuit_breakers",
    "reset_circuit_breaker",
    "reset_all_circuit_breakers",
    "BrowserManager",
    "get_browser_manager",
    "shutdown_browser_manager",
    "BrowserFetchResult",
]
