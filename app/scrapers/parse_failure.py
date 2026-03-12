from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ParseFailureDecision:
    code: str
    message: str
    impact: str
    classification: str = "parse_failure"

    def as_error(self, source: str, url: str) -> str:
        return (
            f"parse_failure[{self.code}] source={source} impact={self.impact} "
            f"url={url} msg={self.message}"
        )


def decide_parse_failure(*, source: str, url: str, found: int, adapter_meta: dict[str, Any] | None) -> ParseFailureDecision | None:
    """Small explicit checklist to avoid empty-success masking parse failures."""
    meta = dict(adapter_meta or {})
    raw_count = int(meta.get("raw_count") or 0)
    normalized_count = int(meta.get("normalized_count") or 0)
    partial_failure = bool(meta.get("partial_failure") or False)

    # Legit empty search page: nothing raw extracted at all.
    if raw_count == 0:
        return None

    # Parser extracted raw cards but nothing survived normalization/final contract.
    if raw_count > 0 and normalized_count == 0 and found == 0:
        return ParseFailureDecision(
            code="raw_without_normalized",
            message="raw cards found but no normalized ad survived parser/contract",
            impact="source_risk_false_empty_success",
        )

    # Parser had warnings/failures and ended with no final listing.
    if raw_count > 0 and found == 0 and partial_failure:
        return ParseFailureDecision(
            code="partial_failure_zero_output",
            message="parser reported partial failure and produced zero final listings",
            impact="source_risk_false_empty_success",
        )

    return None
