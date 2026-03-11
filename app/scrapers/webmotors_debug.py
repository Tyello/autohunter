from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.settings import settings


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class WebmotorsDebugCapture:
    base_dir: str
    metadata_path: str
    html_path: str | None
    screenshot_path: str | None


def _extract_title(html: str) -> str:
    m = _TITLE_RE.search(html or "")
    if not m:
        return ""
    return " ".join((m.group(1) or "").split())[:180]


def _visible_text_snippet(html: str, max_chars: int = 500) -> str:
    clean = _TAG_RE.sub(" ", html or "")
    return " ".join(clean.split())[: max(60, int(max_chars or 500))]


def _base_debug_dir() -> Path:
    return Path(settings.webmotors_debug_dir).expanduser().resolve()


def _prune_old_runs(base: Path, max_runs: int) -> None:
    runs = sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    for stale in runs[max(1, int(max_runs or 1)) :]:
        for child in stale.glob("**/*"):
            if child.is_file():
                child.unlink(missing_ok=True)
        for child in sorted(stale.glob("**/*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        stale.rmdir()


def maybe_capture_webmotors_artifacts(
    *,
    enabled: bool,
    url: str,
    fetch_path: str,
    status: str,
    final_url: str | None,
    html: str | None,
    cards_found: int,
    blocked_reason: str,
    detected_signals: list[str],
    fallback_used: bool,
    attempt: int,
    page_title: str | None = None,
) -> WebmotorsDebugCapture | None:
    if not enabled:
        return None

    base = _base_debug_dir()
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = base / f"{ts}_{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    html_path: str | None = None
    if html:
        html_file = run_dir / "page.html"
        html_file.write_text(html, encoding="utf-8", errors="ignore")
        html_path = str(html_file)

    page_title = page_title or _extract_title(html or "")
    metadata = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "webmotors",
        "status": status,
        "fetch_path": fetch_path,
        "attempt": int(attempt),
        "fallback_used": bool(fallback_used),
        "url_initial": url,
        "url_final": final_url or url,
        "page_title": page_title,
        "visible_text_snippet": _visible_text_snippet(html or "", max_chars=int(settings.webmotors_debug_text_snippet_chars or 500)),
        "cards_found": int(cards_found),
        "blocked_reason": blocked_reason,
        "detected_signals": list(detected_signals or []),
        "artifact_files": {
            "html": html_path,
            "screenshot": None,
        },
    }

    metadata_file = run_dir / "metadata.json"
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_old_runs(base, int(settings.webmotors_debug_max_artifacts or 25))

    return WebmotorsDebugCapture(
        base_dir=str(run_dir),
        metadata_path=str(metadata_file),
        html_path=html_path,
        screenshot_path=None,
    )
