from __future__ import annotations

from dataclasses import dataclass

from src.comparator import ComparisonResult

_CATEGORY_MIN_MARGIN: dict[str, float] = {
    "fragrance": 62.0,
    "skincare":  64.0,
    "wellness":  65.0,
}
_DEFAULT_MIN_MARGIN = 50.0


@dataclass
class ApprovalDecision:
    auto_approved: bool
    reason: str


def _min_margin(category: str) -> float:
    return _CATEGORY_MIN_MARGIN.get(category.lower(), _DEFAULT_MIN_MARGIN)


def approve(result: ComparisonResult) -> ApprovalDecision:
    if result.status == "new_product":
        return ApprovalDecision(False, "New product — requires manual creation in Shopware")

    if result.status == "invalid_data":
        return ApprovalDecision(False, "Missing or unparseable price — requires manual review")

    if result.status == "unchanged":
        return ApprovalDecision(True, "No change — no action required")

    # margin_increase or margin_decrease
    min_margin = _min_margin(result.category)
    new_margin = result.new_margin_pct or 0.0
    current_margin = result.current_margin_pct
    margin_diff = round(new_margin - current_margin, 2) if current_margin is not None else None
    diff_str = f"{margin_diff:+.1f} pp" if margin_diff is not None else "no current margin data"

    # Hard block: margin declined by 2 pp or more
    if margin_diff is not None and margin_diff <= -2.0:
        return ApprovalDecision(
            False,
            f"Margin declined {margin_diff:.1f} pp — exceeds 2 pp limit (new {new_margin:.1f}%, min {min_margin:.1f}%)",
        )

    # Category threshold must still be met
    if new_margin >= min_margin:
        return ApprovalDecision(
            True,
            f"New margin {new_margin:.1f}% meets threshold {min_margin:.1f}% ({diff_str})",
        )

    return ApprovalDecision(
        False,
        f"New margin {new_margin:.1f}% is below threshold {min_margin:.1f}% ({diff_str})",
    )


def approve_all(
    results: list[ComparisonResult],
) -> list[ApprovalDecision]:
    return [approve(r) for r in results]
