from __future__ import annotations

from dataclasses import dataclass

from src.parser import ShopwareProduct, SupplierProduct


@dataclass
class ComparisonResult:
    sku: str
    product_name: str
    brand: str
    category: str
    # Supplier data — None for invalid_data rows (unparseable supplier price)
    new_cost_price: float | None
    new_rrp: float | None
    # Shopware data — None for new products (not yet in Shopware)
    current_cost_price: float | None
    current_rrp: float | None
    active: bool | None
    # Margins — None when the required inputs (cost price, rrp) are absent
    current_margin_pct: float | None  # based on current_rrp and current_cost_price
    new_margin_pct: float | None      # based on new_rrp and new_cost_price
    # One of: new_product | margin_increase | margin_decrease | unchanged | invalid_data
    status: str


def _margin(selling: float, cost: float) -> float:
    if selling <= 0:
        return 0.0
    return (selling - cost) / selling * 100


def _margin_or_none(selling: float | None, cost: float | None) -> float | None:
    """Margin in %, or None when either input is missing."""
    if selling is None or cost is None or selling <= 0:
        return None
    return round(_margin(selling, cost), 2)


def _cents(value: float) -> int:
    """Money as integer cents — avoids float-equality pitfalls on prices."""
    return round(value * 100)


def _same_price(a: float | None, b: float | None) -> bool:
    return _cents(a or 0.0) == _cents(b or 0.0)


def compare(
    supplier_products: list[SupplierProduct],
    shopware_products: list[ShopwareProduct],
) -> list[ComparisonResult]:
    """Compare supplier price lists against existing Shopware data.

    Matching is purely SKU-level — brand plays no part in the comparison. The
    `brand` and `category` on each result are carried over from the matched
    Shopware row for context (and category drives the approval threshold);
    products with no Shopware match have neither.

    Only SKUs present in the supplier input are reported. A Shopware SKU that is
    absent from the input is simply ignored — its absence is not treated as a
    discontinuation, since the input is not assumed to be the full catalogue.
    """
    shopware = {p.sku: p for p in shopware_products}
    results: list[ComparisonResult] = []

    for sup in supplier_products:
        shop = shopware.get(sup.sku)
        current_margin = _margin_or_none(
            shop.current_rrp if shop else None,
            shop.cost_price if shop else None,
        )

        # Missing/unparseable supplier price — surface as invalid_data for
        # manual review rather than dropping the row.
        if sup.cost_price is None or sup.rrp is None:
            results.append(ComparisonResult(
                sku=sup.sku,
                product_name=shop.product_name if shop else "",
                brand=shop.brand if shop else "",
                category=shop.category if shop else "",
                new_cost_price=sup.cost_price,
                new_rrp=sup.rrp,
                current_cost_price=shop.cost_price if shop else None,
                current_rrp=shop.current_rrp if shop else None,
                active=shop.active if shop else None,
                current_margin_pct=current_margin,
                new_margin_pct=None,
                status="invalid_data",
            ))
            continue

        new_margin = round(_margin(sup.rrp, sup.cost_price), 2)

        if shop is None:
            results.append(ComparisonResult(
                sku=sup.sku,
                product_name="",
                brand="",
                category="",
                new_cost_price=sup.cost_price,
                new_rrp=sup.rrp,
                current_cost_price=None,
                current_rrp=None,
                active=None,
                current_margin_pct=None,
                new_margin_pct=new_margin,
                status="new_product",
            ))
            continue

        rrp_same = _same_price(sup.rrp, shop.current_rrp)
        cost_same = _same_price(sup.cost_price, shop.cost_price)

        if rrp_same and cost_same:
            status = "unchanged"
        else:
            effective_current = current_margin if current_margin is not None else 0.0
            if new_margin > effective_current:
                status = "margin_increase"
            elif new_margin < effective_current:
                status = "margin_decrease"
            else:
                status = "unchanged"

        results.append(ComparisonResult(
            sku=sup.sku,
            product_name=shop.product_name,
            brand=shop.brand,
            category=shop.category,
            new_cost_price=sup.cost_price,
            new_rrp=sup.rrp,
            current_cost_price=shop.cost_price,
            current_rrp=shop.current_rrp,
            active=shop.active,
            current_margin_pct=current_margin,
            new_margin_pct=new_margin,
            status=status,
        ))

    return results
