from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


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


def classify_webmotors_error(exc: Exception, *, stage: str, fetch_path: str, attempt: int, fallback_used: bool = False) -> WebmotorsDiagnostic:
    msg = f"{type(exc).__name__}: {exc}"
    low = msg.lower()

    if any(k in low for k in ("proxy", "socks", "407", "tunnel", "proxyconnect")):
        return WebmotorsDiagnostic("PROXY", "proxy_unreachable_or_auth", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used)

    if any(k in low for k in ("dns", "name or service not known", "temporary failure", "connection refused", "net::err_connection", "timed out", "timeout", "ssl", "tls")):
        return WebmotorsDiagnostic("NET", "network_connectivity_or_timeout", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used)

    if any(k in low for k in ("403", "429", "captcha", "challenge", "cloudflare", "perimeterx", "access denied", "bot_challenge")):
        return WebmotorsDiagnostic("BLOCKED", "anti_bot_or_http_block", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used, blocked_likely=True)

    if any(k in low for k in ("playwright", "browser", "context", "target closed", "browser has been closed", "page has been closed")):
        return WebmotorsDiagnostic("BROWSER", "browser_runtime_failure", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used)

    if any(k in low for k in ("parse", "selector", "no_items_parsed", "html_parse")):
        return WebmotorsDiagnostic("PARSER", "listing_parse_failed", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used, backoff_recommended=False)

    return WebmotorsDiagnostic("UNKNOWN", "unclassified_failure", stage, msg[:240], fetch_path, attempt, fallback_used=fallback_used)


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

