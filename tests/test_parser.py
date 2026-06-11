"""Tests for price parsing — the highest-risk function in the tool.

A wrong parse here feeds the margin calc and the approval decision, so the
critical property is: unparseable input must return None, never 0.0.

Run from the project root:  python3 -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

from src.parser import _parse_price


class TestParsePrice(unittest.TestCase):
    def test_plain_english_decimal(self):
        self.assertEqual(_parse_price("12.50"), 12.50)

    def test_european_decimal_comma(self):
        self.assertEqual(_parse_price("27,50"), 27.50)

    def test_european_thousands_and_decimal(self):
        self.assertEqual(_parse_price("1.234,56"), 1234.56)

    def test_english_thousands_and_decimal(self):
        self.assertEqual(_parse_price("1,234.56"), 1234.56)

    def test_nordic_space_thousands(self):
        self.assertEqual(_parse_price("1 234,56"), 1234.56)

    def test_currency_symbols_stripped(self):
        self.assertEqual(_parse_price("€ 49,95"), 49.95)
        self.assertEqual(_parse_price("kr. 100"), 100.0)
        self.assertEqual(_parse_price("100 EUR"), 100.0)

    def test_zero_is_a_valid_price(self):
        # 0 is distinct from "missing" — it must parse, not become None.
        self.assertEqual(_parse_price("0"), 0.0)
        self.assertEqual(_parse_price("0,00"), 0.0)

    # --- The critical contract: bad input -> None, never 0.0 ----------------

    def test_empty_is_none(self):
        self.assertIsNone(_parse_price(""))
        self.assertIsNone(_parse_price("   "))

    def test_non_numeric_is_none(self):
        for bad in ["N/A", "n/a", "-", "TBC", "call us", "ask", "?"]:
            with self.subTest(bad=bad):
                self.assertIsNone(_parse_price(bad))

    def test_currency_only_is_none(self):
        self.assertIsNone(_parse_price("€"))
        self.assertIsNone(_parse_price("kr."))

    def test_bad_input_never_returns_zero(self):
        # Regression guard for the false-auto-approval bug: an unparseable
        # cost must not collapse to 0.0 (which would imply a 100% margin).
        for bad in ["", "N/A", "-", "call us"]:
            with self.subTest(bad=bad):
                self.assertIsNot(_parse_price(bad), 0.0)
                self.assertIsNone(_parse_price(bad))


if __name__ == "__main__":
    unittest.main()
