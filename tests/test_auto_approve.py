"""Tests for the approval policy.

Two independent gates must both pass for a price change to auto-approve:
  1. Margin must not decline by 2 pp or more (hard block).
  2. New margin must still meet the category minimum.

Run from the project root:  python3 -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

from src.auto_approve import _DEFAULT_MIN_MARGIN, approve
from src.comparator import ComparisonResult


def _result(
    status: str,
    *,
    category: str = "fragrance",   # min margin 62.0
    new_margin: float | None = None,
    current_margin: float | None = None,
) -> ComparisonResult:
    return ComparisonResult(
        sku="X-1",
        product_name="Test",
        brand="Test",
        category=category,
        new_cost_price=10.0,
        new_rrp=30.0,
        current_cost_price=10.0,
        current_rrp=30.0,
        active=True,
        current_margin_pct=current_margin,
        new_margin_pct=new_margin,
        status=status,
    )


class TestNonPriceStatuses(unittest.TestCase):
    def test_new_product_is_manual(self):
        self.assertFalse(approve(_result("new_product", new_margin=80.0)).auto_approved)

    def test_invalid_data_is_manual(self):
        d = approve(_result("invalid_data"))
        self.assertFalse(d.auto_approved)
        self.assertIn("manual review", d.reason.lower())

    def test_unchanged_is_approved(self):
        self.assertTrue(approve(_result("unchanged")).auto_approved)


class TestMarginChangeGates(unittest.TestCase):
    def test_above_threshold_small_increase_approved(self):
        # 65% new, 64% current: +1 pp, above the 62% fragrance minimum.
        d = approve(_result("margin_increase", new_margin=65.0, current_margin=64.0))
        self.assertTrue(d.auto_approved)

    def test_below_threshold_rejected(self):
        # 60% new is below the 62% minimum even though margin rose.
        d = approve(_result("margin_increase", new_margin=60.0, current_margin=58.0))
        self.assertFalse(d.auto_approved)
        self.assertIn("below threshold", d.reason)

    def test_at_threshold_exactly_approved(self):
        # new_margin == min_margin must pass (>=).
        d = approve(_result("margin_decrease", new_margin=62.0, current_margin=62.5))
        self.assertTrue(d.auto_approved)

    def test_decline_of_exactly_two_pp_blocked(self):
        # Hard block at -2.0 even if the new margin clears the minimum.
        d = approve(_result("margin_decrease", new_margin=70.0, current_margin=72.0))
        self.assertFalse(d.auto_approved)
        self.assertIn("declined", d.reason.lower())

    def test_decline_just_under_two_pp_allowed(self):
        # -1.9 pp and still above the minimum -> approved.
        d = approve(_result("margin_decrease", new_margin=70.1, current_margin=72.0))
        self.assertTrue(d.auto_approved)

    def test_hard_block_takes_priority_over_threshold(self):
        # A 3 pp decline is blocked regardless of an otherwise-healthy margin.
        d = approve(_result("margin_decrease", new_margin=80.0, current_margin=83.0))
        self.assertFalse(d.auto_approved)
        self.assertIn("declined", d.reason.lower())

    def test_missing_current_margin_skips_hard_block(self):
        # No current margin -> no decline to measure -> decided on threshold only.
        d = approve(_result("margin_increase", new_margin=70.0, current_margin=None))
        self.assertTrue(d.auto_approved)


class TestCategoryThresholds(unittest.TestCase):
    def test_unknown_category_uses_default(self):
        # Default min is 50%; 55% clears it.
        d = approve(_result("margin_increase", category="unknown",
                             new_margin=55.0, current_margin=54.0))
        self.assertTrue(d.auto_approved)
        self.assertIn(f"{_DEFAULT_MIN_MARGIN:.1f}", d.reason)

    def test_category_lookup_is_case_insensitive(self):
        d = approve(_result("margin_increase", category="FRAGRANCE",
                             new_margin=63.0, current_margin=62.5))
        self.assertTrue(d.auto_approved)


if __name__ == "__main__":
    unittest.main()
