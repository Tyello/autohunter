from __future__ import annotations

from typing import Dict, Iterable, Set


# Canonical aliases for common typos / shortcuts in admin commands.
# Keep this conservative; only map what you're sure about.
SOURCE_ALIASES: Dict[str, str] = {
    "webmotor": "webmotors",
    "wm": "webmotors",
    "web-motors": "webmotors",
}


def canonical_source_name(name: str) -> str:
    if not name:
        return name
    k = name.strip().lower()
    return SOURCE_ALIASES.get(k, k)


def validate_source_name(name: str, known_sources: Iterable[str]) -> None:
    canon = canonical_source_name(name)
    known: Set[str] = {s.strip().lower() for s in known_sources if s}
    if canon not in known:
        raise ValueError(f"unknown source '{name}' (canonical='{canon}')")
