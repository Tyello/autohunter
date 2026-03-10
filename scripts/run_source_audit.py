from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.runtime_paths import source_audit_dir
from app.services.source_audit_report_service import write_reports


def _load_samples(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        raise ValueError("JSON input must be an array of sample rows")

    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate source audit coverage matrix.")
    ap.add_argument("--input", required=True, help="JSON or JSONL with field audit rows")
    ap.add_argument("--out", default=str(source_audit_dir().parent / "source_audit_reports"), help="Output directory")
    args = ap.parse_args()

    rows = _load_samples(Path(args.input))
    outputs = write_reports(rows, Path(args.out))
    print(json.dumps({k: str(v) for k, v in outputs.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
