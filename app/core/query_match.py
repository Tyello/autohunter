"""Lightweight query matching for classifieds titles.

Why this exists:
- Classic substring contains() is too weak (brings 'Civic 2015 LXR' when you want 'Civic SI')
- Full NLP is too heavy for Raspberry Pi 3

Approach:
- Normalize + tokenize
- Maintain include/exclude token lists
- Score matches; require minimum score

You can start with presets (build_preset_rule) and evolve per wishlist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .text_norm import normalize


@dataclass(frozen=True)
class MatchRule:
    name: str
    include_any: tuple[str, ...] = field(default_factory=tuple)
    include_all: tuple[str, ...] = field(default_factory=tuple)
    exclude_any: tuple[str, ...] = field(default_factory=tuple)
    min_score: int = 1


def _contains_any(tokset: set[str], words: Sequence[str]) -> bool:
    return any(w in tokset for w in words)


def _contains_all(tokset: set[str], words: Sequence[str]) -> bool:
    return all(w in tokset for w in words)


def match_score(title: str, rule: MatchRule) -> int:
    """Return an integer score; 0 means 'no match'."""
    t = normalize(title)
    if not t:
        return 0
    tok = set(t.split())

    # hard excludes first
    if rule.exclude_any and _contains_any(tok, rule.exclude_any):
        return 0

    # require all tokens
    if rule.include_all and not _contains_all(tok, rule.include_all):
        return 0

    score = 0

    # score: each include_all is worth 2, include_any worth 1
    score += 2 * sum(1 for w in rule.include_all if w in tok)
    if rule.include_any:
        score += 1 if _contains_any(tok, rule.include_any) else 0
    else:
        # if no include_any, accept if include_all passed
        score += 1

    return score if score >= rule.min_score else 0


def is_match(title: str, rule: MatchRule) -> bool:
    return match_score(title, rule) > 0


# ---- Presets (start here; adjust per community slang) ----

_TYPE_R_EXCLUDES = ("type", "r", "typer")  # normalize() splits 'type-r' into 'type r'


def build_preset_rule(wishlist_name: str) -> MatchRule:
    """Generate a conservative rule from a wishlist name.

    Examples:
      - 'civic si' => requires 'civic' + one of ('si','sir','vtec') and excludes 'type r'
      - 'civic hatch' => requires 'civic' + one of ('hatch','hatchback') and excludes 'type r'
    """
    wl = normalize(wishlist_name)
    wl_tokens = wl.split()

    anchor = wl_tokens[0] if wl_tokens else ""
    rest = wl_tokens[1:]

    include_all: list[str] = []
    include_any: list[str] = []
    exclude_any: list[str] = []

    if anchor:
        include_all.append(anchor)

    if rest:
        k = rest[0]
        if k in {"si", "sir"}:
            include_any += ["si", "sir", "vtec"]
            exclude_any += list(_TYPE_R_EXCLUDES)
            min_score = 3  # civic(2) + any(1)
        elif k in {"hatch", "hatchback"}:
            include_any += ["hatch", "hatchback"]
            exclude_any += list(_TYPE_R_EXCLUDES)
            min_score = 3
        else:
            include_any += rest
            min_score = 3 if anchor and rest else 1
    else:
        min_score = 1

    return MatchRule(
        name=wishlist_name,
        include_any=tuple(dict.fromkeys(include_any)),
        include_all=tuple(dict.fromkeys(include_all)),
        exclude_any=tuple(dict.fromkeys(exclude_any)),
        min_score=min_score,
    )


def explain(title: str, rule: MatchRule) -> dict:
    """Explain matching decisions (useful for debugging false positives)."""
    t = normalize(title)
    tok = set(t.split())
    return {
        "title_norm": t,
        "tokens": sorted(tok),
        "include_all_ok": _contains_all(tok, rule.include_all) if rule.include_all else True,
        "include_any_ok": _contains_any(tok, rule.include_any) if rule.include_any else True,
        "excluded": [w for w in rule.exclude_any if w in tok],
        "score": match_score(title, rule),
        "min_score": rule.min_score,
        "rule": {
            "name": rule.name,
            "include_all": rule.include_all,
            "include_any": rule.include_any,
            "exclude_any": rule.exclude_any,
        },
    }
