from __future__ import annotations

from app.health.models import RunSummary


def top_buckets(buckets: dict[str, int], k: int = 3) -> list[tuple[str, int]]:
    items = [(str(name), int(v or 0)) for name, v in (buckets or {}).items()]
    items = [it for it in items if it[1] > 0]
    items.sort(key=lambda x: (-x[1], x[0]))
    return items[: max(1, int(k or 3))]


def explain_queued_zero(summary: RunSummary) -> str:
    top = top_buckets(summary.reason_buckets, k=3)
    if not top:
        return "queued=0 porque: sem razões contabilizadas"
    reasons = " ".join(f"{name}={value}" for name, value in top)
    return f"queued=0 porque: {reasons}"


def add_anomaly_notes(summary: RunSummary) -> RunSummary:
    if int(summary.found or 0) == 0:
        summary.notes.append("found=0 suspeito (possível mudança de layout/bloqueio)")

    if int(summary.matched or 0) > 0 and int(summary.queued or 0) == 0:
        summary.notes.append(explain_queued_zero(summary))

    return summary
