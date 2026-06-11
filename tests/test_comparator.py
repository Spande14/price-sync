"""Tests for the comparison/status logic.

Run from the project root:  python3 -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

from src.comparator import compare
from src.parser import ShopwareProduct, SupplierProduct


def _shop(sku, rrp, cost, brand="AromaBelle", category="Fragrance"):
    return ShopwareProduct(sku=sku, product_name=sku, brand=brand,
                           category=category, current_rrp=rrp, cost_price=cost)


def _by_sku(results):
    return {r.sku: r for r in results}


class TestStatus(unittest.TestCase):
    def test_margin_increase_when_rrp_rises(self):
        # RRP up, cost unchanged -> new margin 81.8% vs 80% -> margin_increase.
        sup = [SupplierProduct("A", cost_price=10.0, rrp=55.0)]
        shop = [_shop("A", 50.0, 10.0)]
        self.assertEqual(_by_sku(compare(sup, shop))["A"].status, "margin_increase")

    def test_margin_decrease_when_rrp_falls(self):
        # RRP down, cost unchanged -> new margin 77.8% vs 80% -> margin_decrease.
        sup = [SupplierProduct("A", cost_price=10.0, rrp=45.0)]
        shop = [_shop("A", 50.0, 10.0)]
        self.assertEqual(_by_sku(compare(sup, shop))["A"].status, "margin_decrease")

    def test_margin_decrease_when_cost_rises(self):
        # RRP identical, cost up -> new margin 76% vs 80% -> margin_decrease.
        sup = [SupplierProduct("A", cost_price=12.0, rrp=50.0)]
        shop = [_shop("A", 50.0, 10.0)]
        self.assertEqual(_by_sku(compare(sup, shop))["A"].status, "margin_decrease")

    def test_margin_increase_when_cost_falls(self):
        # RRP identical, cost down -> new margin 84% vs 80% -> margin_increase.
        sup = [SupplierProduct("A", cost_price=8.0, rrp=50.0)]
        shop = [_shop("A", 50.0, 10.0)]
        self.assertEqual(_by_sku(compare(sup, shop))["A"].status, "margin_increase")

    def test_unchanged_requires_both_equal(self):
        sup = [SupplierProduct("A", cost_price=10.0, rrp=50.0)]
        shop = [_shop("A", 50.0, 10.0)]
        self.assertEqual(_by_sku(compare(sup, shop))["A"].status, "unchanged")

    def test_new_product(self):
        sup = [SupplierProduct("NEW", cost_price=10.0, rrp=50.0)]
        self.assertEqual(_by_sku(compare(sup, []))["NEW"].status, "new_product")

    def test_shopware_only_sku_is_ignored(self):
        # A SKU present only in Shopware (not in any supplier file) is not
        # reported at all — the tool only covers SKUs in the supplier input.
        shop = [_shop("OLD", 50.0, 10.0)]
        self.assertEqual(compare([], shop), [])


class TestCentsComparison(unittest.TestCase):
    def test_float_noise_treated_as_equal(self):
        # 0.1 + 0.2 == 0.30000000000000004 must still read as unchanged.
        sup = [SupplierProduct("A", cost_price=0.1 + 0.2, rrp=50.0)]
        shop = [_shop("A", 50.0, 0.3)]
        self.assertEqual(_by_sku(compare(sup, shop))["A"].status, "unchanged")


class TestInvalidData(unittest.TestCase):
    def test_none_price_is_invalid_data(self):
        sup = [SupplierProduct("A", cost_price=None, rrp=50.0)]
        shop = [_shop("A", 50.0, 10.0)]
        r = _by_sku(compare(sup, shop))["A"]
        self.assertEqual(r.status, "invalid_data")
        self.assertIsNone(r.new_margin_pct)

    def test_invalid_row_produces_single_result(self):
        # An unpriced supplier row yields exactly one invalid_data result —
        # no phantom duplicate for the same SKU.
        sup = [SupplierProduct("A", cost_price=None, rrp=None)]
        shop = [_shop("A", 50.0, 10.0)]
        results = compare(sup, shop)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "invalid_data")

    def test_invalid_row_keeps_current_data_visible(self):
        sup = [SupplierProduct("A", cost_price=None, rrp=50.0)]
        shop = [_shop("A", 48.0, 10.0)]
        r = _by_sku(compare(sup, shop))["A"]
        self.assertEqual(r.current_rrp, 48.0)
        self.assertEqual(r.current_cost_price, 10.0)


if __name__ == "__main__":
    unittest.main()
