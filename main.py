#!/usr/bin/env python3
"""
price-sync — synchronise supplier price lists with Shopware 6.

Usage:
    python3 main.py

Place supplier price lists in data/input/ and run the script. Every file in
the folder is loaded and all products are compared against the Shopware export
on a SKU level — brands and filenames are irrelevant.
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.auto_approve import ApprovalDecision, approve_all
from src.comparator import ComparisonResult, compare
from src.parser import SupplierProduct, load_shopware_data, load_supplier_pricelist
from src.reporter import generate_report

INPUT_DIR = Path("data/input")
SHOPWARE_FILE = Path("data/existing/shopware.csv")
OUTPUT = Path("output")


def _discover_supplier_files() -> list[Path]:
    """Return all supplier price list files in data/input/ (any name, CSV or xlsx)."""
    files = [
        p for p in INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in (".csv", ".xlsx")
    ]
    return sorted(files)


def _combine(per_file: list[tuple[str, list[SupplierProduct]]]) -> list[SupplierProduct]:
    """Pool products from every input file, keyed by SKU.

    SKUs are global: if the same SKU appears in more than one file the last
    occurrence wins and a warning names the conflict (mirroring the within-file
    duplicate behaviour in the parser).
    """
    source: dict[str, str] = {}
    combined: dict[str, SupplierProduct] = {}
    conflicts: list[str] = []
    for filename, products in per_file:
        for p in products:
            if p.sku in source and source[p.sku] != filename:
                conflicts.append(f"{p.sku} ({source[p.sku]} -> {filename})")
            source[p.sku] = filename
            combined[p.sku] = p
    if conflicts:
        print(
            f"  WARNING: {len(conflicts)} SKU(s) appear in multiple files — "
            f"keeping last occurrence: {', '.join(conflicts)}",
            file=sys.stderr,
        )
    return list(combined.values())


def _print_summary(
    results: list[ComparisonResult],
    decisions: list[ApprovalDecision],
) -> None:
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1

    auto = sum(1 for d in decisions if d.auto_approved)
    manual = len(decisions) - auto

    parts = []
    for key, label in [
        ("price_increase", "increases"),
        ("price_decrease", "decreases"),
        ("cost_change", "cost changes"),
        ("unchanged", "unchanged"),
        ("new_product", "new"),
        ("invalid_data", "invalid"),
    ]:
        n = by_status.get(key, 0)
        if n:
            parts.append(f"{n} {label}")

    print(f"  Results:  {len(results)} total  ({', '.join(parts)})")
    print(f"  Approval: {auto} auto-approved  |  {manual} for manual review")


def main() -> None:
    supplier_files = _discover_supplier_files()
    if not supplier_files:
        print("No price lists found in data/input/ — exiting.")
        sys.exit(1)

    if not SHOPWARE_FILE.exists():
        print(f"Shopware data file not found: {SHOPWARE_FILE} — exiting.")
        sys.exit(1)

    all_shopware = load_shopware_data(SHOPWARE_FILE)

    per_file: list[tuple[str, list[SupplierProduct]]] = []
    skipped: list[str] = []
    for path in supplier_files:
        try:
            products = load_supplier_pricelist(path)
        except (ValueError, ImportError, OSError) as exc:
            # One bad file must not abort the whole batch.
            print(f"  SKIPPED ({path.name}): {exc}", file=sys.stderr)
            skipped.append(path.name)
            continue
        print(f"  Loaded {path.name}: {len(products)} products")
        per_file.append((path.name, products))

    if not per_file:
        print("No price lists could be processed — exiting.")
        sys.exit(1)

    supplier_products = _combine(per_file)

    print(f"\n{'─' * 50}")
    print(
        f"  Comparing {len(supplier_products)} supplier products against "
        f"{len(all_shopware)} Shopware products (SKU level)"
    )
    print(f"{'─' * 50}")

    results = compare(supplier_products, all_shopware)
    decisions = approve_all(results)
    _print_summary(results, decisions)

    csv_p = generate_report([("all", results, decisions)], OUTPUT)

    print(f"\n{'─' * 50}")
    print(f"  Report: {csv_p}")
    if skipped:
        print(f"  Skipped {len(skipped)} file(s): {', '.join(skipped)}")
    print(f"  Reports saved to: {OUTPUT}/")
    print(f"{'─' * 50}\n")


if __name__ == "__main__":
    main()
