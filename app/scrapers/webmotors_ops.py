from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from app.scrapers.base import FetchBlocked


WM_DIAG_PREFIX = "WM_DIAG::"


@dataclass(frozen=True)
class WebmotorsDiagnostic:
    bucket: str
    reason: str
    stage: str
    evidence: str
    fetch_path: str
    attempt: int
    fallback_used: bool = False
    blocked_likely: bool = False
    backoff_recommended: bool = True

    def as_payload(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "reason": self.reason,
            "stage": self.stage,
            "evidence": self.evidence,
            "fetch_path": self.fetch_path,
            "attempt": int(self.attempt),
            "fallback_used": bool(self.fallback_used),
            "blocked_likely": bool(self.blocked_likely),
            "backoff_recommended": bool(self.backoff_recommended),
        }


def _safe_error_message(exc: Exception) -> str:
    try:
        return f"{type(exc).__name__}: {exc}"
    except Exception as err:
        return f"{type(exc).__name__}: <unprintable_exc:{type(err).__name__}>"


def classify_webmotors_error(exc: Exception, *, stage: str, fetch_path: str, attempt: int, fallback_used: bool = False) -> WebmotorsDiagnostic:
    msg = _safe_error_message(exc)
    low = msg.lower()
    try:
        if isinstance(exc, FetchBlocked):
            reason = str(getattr(exc, "reason", "") or "").lower()
            status = int(getattr(exc, "status_code", 0) or 0)
            if status in {403, 429} or any(k in reason for k in ("challenge", "captcha", "bot", "cloudflare", "perimeterx", "datadome", "access denied", "http_status")):
                return WebmotorsDiagnostic("BLOCKED", "anti_bot_or_http_block", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used, blocked_likely=True)
            if status == 407 or any(k in reason for k in ("proxy", "tunnel", "socks", "proxyconnect")):
                return WebmotorsDiagnostic("PROXY", "proxy_unreachable_or_auth", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used)

        if any(k in low for k in ("proxy", "socks", "407", "tunnel", "proxyconnect")):
            return WebmotorsDiagnostic("PROXY", "proxy_unreachable_or_auth", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used)

        if any(k in low for k in ("dns", "name or service not known", "temporary failure", "connection refused", "net::err_connection", "timed out", "timeout", "ssl", "tls")):
            return WebmotorsDiagnostic("NET", "network_connectivity_or_timeout", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used)

        if any(k in low for k in ("403", "429", "captcha", "challenge", "cloudflare", "perimeterx", "datadome", "access denied", "bot_challenge")):
            return WebmotorsDiagnostic("BLOCKED", "anti_bot_or_http_block", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used, blocked_likely=True)

        if any(k in low for k in ("playwright", "browser", "context", "target closed", "browser has been closed", "page has been closed", "new_page")):
            return WebmotorsDiagnostic("BROWSER", "browser_runtime_failure", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used)

        if any(k in low for k in ("parse", "selector", "no_items_parsed", "html_parse")):
            return WebmotorsDiagnostic("PARSER", "listing_parse_failed", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used, backoff_recommended=False)

        return WebmotorsDiagnostic("UNKNOWN", "unclassified_failure", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used)
    except Exception as mapping_err:
        safe_evidence = (
            f"mapping_error={type(mapping_err).__name__}: {mapping_err}; "
            f"original={msg}"
        )
        return WebmotorsDiagnostic("UNKNOWN", "diagnostic_mapping_error", stage, safe_evidence[:240], fetch_path, attempt, fallback_used=fallback_used)


def encode_webmotors_diag(diag: WebmotorsDiagnostic) -> str:
    return WM_DIAG_PREFIX + json.dumps(diag.as_payload(), ensure_ascii=False, separators=(",", ":"))


def extract_webmotors_diag(err: Optional[str]) -> Optional[dict[str, Any]]:
    s = (err or "").strip()
    if WM_DIAG_PREFIX not in s:
        return None
    _, _, tail = s.partition(WM_DIAG_PREFIX)
    if not tail:
        return None
    try:
        data = json.loads(tail)
    except Exception:
        return None
    return data if isinstance(data, dict) else None
