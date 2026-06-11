from __future__ import annotations

import csv
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import TYPE_CHECKING

from src.comparator import ComparisonResult

if TYPE_CHECKING:
    from src.auto_approve import ApprovalDecision

_CSV_FIELDS = [
    "sku", "brand", "category", "product_name", "status",
    "current_cost_price", "new_cost_price",
    "current_rrp", "new_rrp",
    "current_margin_pct", "new_margin_pct",
]
_CSV_FIELDS_WITH_APPROVAL = _CSV_FIELDS + ["auto_approved", "reason"]


def _csv_val(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _to_csv_row(r: ComparisonResult) -> dict[str, str]:
    return {f: _csv_val(getattr(r, f)) for f in _CSV_FIELDS}


def generate_report(
    brand_data: list[tuple[str, list[ComparisonResult], list[ApprovalDecision] | None]],
    output_dir: Path,
) -> Path:
    """Write combined_YYYY-MM-DD_HHMMSS.csv combining all processed brands."""
    has_decisions = any(decisions is not None for _, _, decisions in brand_data)
    fields = _CSV_FIELDS_WITH_APPROVAL if has_decisions else _CSV_FIELDS
    output_dir.mkdir(parents=True, exist_ok=True)
    # UTC + 'Z' suffix so the timestamp is unambiguous across machines.
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%SZ")
    path = output_dir / f"combined_{stamp}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=",")
        writer.writeheader()
        for _, results, decisions in brand_data:
            # zip_longest guards against any results/decisions length mismatch
            # instead of silently mispairing by index.
            for r, d in zip_longest(results, decisions or []):
                if r is None:
                    continue
                row = _to_csv_row(r)
                if has_decisions:
                    row["auto_approved"] = "" if d is None else ("true" if d.auto_approved else "false")
                    row["reason"] = "" if d is None else d.reason
                writer.writerow(row)
    return path
