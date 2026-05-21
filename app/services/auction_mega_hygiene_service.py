from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.models.auction_lot import AuctionLot
from app.models.source_config import SourceConfig
from app.sources.auctions.mega import audit_mega_persisted_lot


def run_mega_hygiene(db: Session, *, apply: bool = False, limit: int = 200) -> dict[str, Any]:
    source = "mega_auctions"
    cfg = db.query(SourceConfig).filter(SourceConfig.source == source, SourceConfig.source_type == "auction").first()
    is_experimental = bool(cfg and str(cfg.status or "").lower().startswith("experimental"))
    lots = db.query(AuctionLot).filter(AuctionLot.source == source).order_by(AuctionLot.updated_at.desc()).limit(max(1, limit)).all()
    issue_counts: Counter[str] = Counter()
    updates = 0
    examples: list[dict[str, Any]] = []
    blocked = bool(apply and not is_experimental)
    reason = "source_not_experimental" if blocked else None
    for lot in lots:
        audit = audit_mega_persisted_lot(lot)
        issues = list(audit["issues"])
        for issue in issues:
            issue_counts[issue] += 1
        if issues and len(examples) < 5:
            examples.append({
                "external_id": lot.external_id,
                "title": lot.title,
                "url": lot.url,
                "issues": issues,
                "suggested_updates": audit["suggested_updates"],
            })
        if apply and (not blocked) and audit["suggested_updates"]:
            patch = dict(audit["suggested_updates"])
            extras_patch = patch.pop("extras", None)
            for key, value in patch.items():
                setattr(lot, key, value)
            if isinstance(extras_patch, dict):
                existing = dict(lot.extras or {})
                existing.update(extras_patch)
                lot.extras = existing
            updates += 1
    if apply and not blocked:
        db.commit()
    return {
        "source": source,
        "is_experimental": is_experimental,
        "analyzed": len(lots),
        "issue_counts": dict(issue_counts),
        "updated": updates,
        "examples": examples,
        "dry_run": not apply,
        "blocked": blocked,
        "reason": reason,
    }
