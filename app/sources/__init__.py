"""Source plugins registry.

This package centralizes all listing sources (Mercado Livre, OLX, etc.) behind a
single pluggable interface.

NOTE: This module uses lazy imports to avoid circular-import issues during startup.
"""

from __future__ import annotations


def get_source(name: str):
    from .registry import get_source as _get_source
    return _get_source(name)


def list_sources():
    from .registry import list_sources as _list_sources
    return _list_sources()


def list_enabled_sources():
    from .registry import list_enabled_sources as _list_enabled_sources
    return _list_enabled_sources()
