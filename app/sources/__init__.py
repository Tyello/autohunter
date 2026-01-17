"""Source plugins registry.

This package centralizes all listing sources (Mercado Livre, OLX, etc.) behind a
single pluggable interface.

Design goals:
- Keep the scheduler and manual search simple (iterate plugins).
- Make it trivial to add a new source without editing 6 different files.
- Allow "not implemented" sources (SPA/JS-heavy) to exist in the registry,
  but be disabled by default.
"""

from .registry import get_source, list_sources, list_enabled_sources  # noqa: F401
