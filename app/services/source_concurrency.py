"""
Thread-safe per-source semaphore management for concurrency control.
Etapa 2: Módulo de semáforo por-source
"""

import threading
from typing import Dict

from app.core.settings import settings

# Module-level state (protected by _lock)
_semaphores: Dict[str, threading.Semaphore] = {}
_lock = threading.Lock()


def get_source_semaphore(source: str) -> threading.Semaphore:
    """
    Get or create a semaphore for the given source.

    Thread-safe: uses a module-level lock to protect creation.
    Cached: repeated calls with the same normalized source return the same instance.
    Normalized key: (source or "").strip().lower()

    Size is determined on first creation from settings.source_max_concurrent_per_source
    with a minimum of 1.

    Args:
        source: Source name (may be None, empty, or mixed-case)

    Returns:
        threading.Semaphore for that source
    """
    # Normalize the source key (same convention as source_execution_service.py)
    normalized_key = (source or "").strip().lower()

    # Fast path: if already cached, return it (read-only, no lock needed for dict lookup)
    if normalized_key in _semaphores:
        return _semaphores[normalized_key]

    # Slow path: create a new semaphore, protected by lock
    with _lock:
        # Double-check pattern: another thread might have created it while we were waiting for the lock
        if normalized_key in _semaphores:
            return _semaphores[normalized_key]

        # Create the semaphore with size from settings, minimum 1
        semaphore_size = max(1, int(settings.source_max_concurrent_per_source or 1))
        semaphore = threading.Semaphore(semaphore_size)

        # Store in cache
        _semaphores[normalized_key] = semaphore

        return semaphore
