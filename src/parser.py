from __future__ import annotations

import csv
import io
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]

# ---------------------------------------------------------------------------
# Supplier column alias map
#
# Supplier files vary widely in column naming. Keys are canonical field names;
# values are normalised aliases (_normalize_col applied) the supplier might use.
#
# Note on precision: the `sku` aliases are deliberately conservative. Generic
# tokens like `ean`, `id` and `ref` are excluded — an EAN is a barcode (not the
# article number), and `id`/`ref` routinely refer to row indices or internal
# references. Mapping the wrong column to `sku` is the worst failure mode here:
# it breaks the SKU overlap, so every product reads as "new" and brand
# detection silently fails.
# ---------------------------------------------------------------------------

_SUPPLIER_ALIASES: dict[str, set[str]] = {
    "sku": {
        "sku", "articleno", "itemcode", "varenummer", "artikelnr",
        "artnr", "article", "item", "productnumber", "productno",
        "productcode", "itemno", "code", "reference",
    },
    "cost_price": {
        "indkobspris", "cost", "purchaseprice", "netto", "kostpris",
        "buyprice", "netprice", "unitcost", "costprice", "kost",
        "inpris", "indkpris", "costpriceeur", "wholesaleprice",
    },
    "rrp": {
        "rrp", "msrp", "vejlpris", "listprice", "vejledendepris",
        "recommendedprice", "uvp", "srp", "suggestedprice",
        "anbefaledudsalgspris", "udsalgspris", "rrpeur", "sellprice",
    },
}
_SUPPLIER_REQUIRED = {"sku", "cost_price", "rrp"}


# ---------------------------------------------------------------------------
# Dataclasses
#
# Prices are Optional: None means "absent or unparseable", which is distinct
# from 0.0 (a real, if suspicious, price). The comparator surfaces None-priced
# supplier rows as `invalid_data` so they are routed to manual review rather
# than silently defaulting to a 100% margin.
# ---------------------------------------------------------------------------

@dataclass
class SupplierProduct:
    sku: str
    cost_price: float | None
    rrp: float | None


@dataclass
class ShopwareProduct:
    sku: str
    product_name: str = ""
    brand: str = ""
    category: str = ""
    current_rrp: float | None = None
    cost_price: float | None = None
    active: bool = True


# ---------------------------------------------------------------------------
# Header normalisation + alias mapping (supplier files only)
# ---------------------------------------------------------------------------

def _normalize_col(s: str) -> str:
    """Transliterates Nordic chars then strips everything that isn't a-z or 0-9."""
    s = s.lower()
    for src, dst in [("ø", "o"), ("æ", "ae"), ("å", "aa"),
                     ("ö", "o"), ("ä", "ae"), ("ü", "u")]:
        s = s.replace(src, dst)
    return re.sub(r"[^a-z0-9]", "", s)


def _map_headers(
    actual_headers: list[str],
    alias_map: dict[str, set[str]],
    required: set[str],
    filename: str,
) -> dict[str, str]:
    """Map canonical field names to actual column headers via alias lookup.

    Returns {canonical: actual_header}.
    Raises ValueError if any required field has no matching header.
    """
    norm_to_actual: dict[str, str] = {}
    for h in actual_headers:
        norm_to_actual.setdefault(_normalize_col(h), h)

    result: dict[str, str] = {}
    for canonical, aliases in alias_map.items():
        for alias in aliases:
            if alias in norm_to_actual:
                result[canonical] = norm_to_actual[alias]
                break

    missing = required - set(result.keys())
    if missing:
        raise ValueError(
            f"{filename}: unrecognised columns: {', '.join(sorted(missing))}. "
            f"Available columns: {', '.join(actual_headers) or '(none)'}"
        )
    return result


def _get(row: dict[str, str], col_map: dict[str, str], canonical: str, default: str = "") -> str:
    actual = col_map.get(canonical)
    return row.get(actual, default).strip() if actual else default


# ---------------------------------------------------------------------------
# Header-row detection (skips supplier metadata rows above the actual header)
# ---------------------------------------------------------------------------

def _find_header_row_idx(
    lines: list[str],
    delimiter: str,
    alias_map: dict[str, set[str]],
    required: set[str],
) -> int:
    required_aliases = {
        alias for field in required for alias in alias_map.get(field, set())
    }
    all_known = {alias for aliases in alias_map.values() for alias in aliases}

    for i, line in enumerate(lines[:20]):
        cols = {_normalize_col(c) for c in line.split(delimiter) if c.strip()}
        if cols & required_aliases:
            return i
        if len(cols & all_known) >= 2:
            return i
    return 0


# ---------------------------------------------------------------------------
# Number parsing
# ---------------------------------------------------------------------------

_CURRENCY_RE = re.compile(
    r"[€$£¥]|kr\.?|dkk|eur|usd|gbp|chf|nok|sek",
    flags=re.IGNORECASE,
)


def _parse_price(value: str) -> float | None:
    """Parse a price string handling English, European/Danish, and Nordic formats.

    Returns None when the value is absent or cannot be parsed — callers MUST
    treat None as "no price", never as 0.0. Defaulting an unparseable cost to
    0.0 would silently produce a 100% margin and a false auto-approval.
    """
    s = value.strip()
    if not s:
        return None
    try:
        s = _CURRENCY_RE.sub("", s).strip()
        if not s:
            return None
        s = s.replace(" ", "").replace(" ", "")
        if not s:
            return None
        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_comma > last_dot:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
        return float(s)
    except (ValueError, AttributeError):
        return None


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "ja", "yes"}


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def _dedup(products: list, filename: str) -> list:
    seen: dict[str, int] = {}
    for i, p in enumerate(products):
        seen[p.sku] = i

    dupes = sorted({p.sku for i, p in enumerate(products) if seen[p.sku] != i})
    if dupes:
        print(
            f"  WARNING ({filename}): {len(dupes)} duplicate SKU(s) found — "
            f"keeping last occurrence: {', '.join(dupes)}",
            file=sys.stderr,
        )

    deduped: dict[str, object] = {}
    for p in products:
        deduped[p.sku] = p
    return list(deduped.values())


# ---------------------------------------------------------------------------
# Supplier file reader (CSV and xlsx, with alias mapping)
# ---------------------------------------------------------------------------

def _detect_encoding(filepath: Path) -> str:
    for enc in _ENCODINGS:
        try:
            with filepath.open(encoding=enc) as f:
                f.read(1024)
            return enc
        except (UnicodeDecodeError, ValueError):
            continue
    return "latin-1"


def _detect_delimiter(first_nonempty_line: str) -> str:
    return ";" if first_nonempty_line.count(";") > first_nonempty_line.count(",") else ","


def _load_supplier_csv(filepath: Path) -> tuple[list[str], list[dict[str, str]]]:
    encoding = _detect_encoding(filepath)
    with filepath.open(encoding=encoding, newline="") as f:
        content = f.read()

    lines = content.splitlines()
    if not lines:
        return [], []

    first_nonempty = next((ln for ln in lines if ln.strip()), lines[0])
    delimiter = _detect_delimiter(first_nonempty)
    header_idx = _find_header_row_idx(lines, delimiter, _SUPPLIER_ALIASES, _SUPPLIER_REQUIRED)

    body = "\n".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(body), delimiter=delimiter)
    headers = [h for h in (reader.fieldnames or []) if h is not None]
    rows = [
        {k: str(v or "").strip() for k, v in row.items() if k is not None}
        for row in reader
    ]
    return headers, rows


def _load_supplier_xlsx(filepath: Path) -> tuple[list[str], list[dict[str, str]]]:
    if filepath.suffix.lower() == ".xls":
        raise ValueError(
            f"{filepath.name}: the legacy .xls format is not supported. "
            "Save the file as .xlsx and try again."
        )
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError:
        raise ImportError(
            "openpyxl is required to read .xlsx files. "
            "Install with: pip install openpyxl"
        )

    all_known = {alias for aliases in _SUPPLIER_ALIASES.values() for alias in aliases}
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    headers: list[str] | None = None
    rows: list[dict[str, str]] = []

    for excel_row in ws.iter_rows(values_only=True):
        cells = [str(c).strip() if c is not None else "" for c in excel_row]
        if not any(cells):
            continue
        if headers is None:
            if {_normalize_col(c) for c in cells if c} & all_known:
                headers = cells
        else:
            rows.append({
                headers[i]: (cells[i] if i < len(cells) else "")
                for i in range(len(headers))
            })

    wb.close()
    return headers or [], rows


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_supplier_pricelist(filepath: Path) -> list[SupplierProduct]:
    """Load a supplier price list from CSV or xlsx.

    Rows with a SKU but a missing/unparseable cost or RRP are kept (with None
    prices) and a warning is printed — they are surfaced as `invalid_data` by
    the comparator rather than being silently dropped.
    """
    if filepath.suffix.lower() in (".xlsx", ".xls"):
        headers, rows = _load_supplier_xlsx(filepath)
    else:
        headers, rows = _load_supplier_csv(filepath)

    col_map = _map_headers(headers, _SUPPLIER_ALIASES, _SUPPLIER_REQUIRED, filepath.name)

    products: list[SupplierProduct] = []
    bad: list[str] = []
    for row in rows:
        sku = _get(row, col_map, "sku")
        if not sku:
            continue
        cost = _parse_price(_get(row, col_map, "cost_price"))
        rrp = _parse_price(_get(row, col_map, "rrp"))
        if cost is None or rrp is None:
            bad.append(sku)
        products.append(SupplierProduct(sku=sku, cost_price=cost, rrp=rrp))

    if bad:
        print(
            f"  WARNING ({filepath.name}): {len(bad)} row(s) with missing/unparseable "
            f"price — flagged for manual review: {', '.join(bad)}",
            file=sys.stderr,
        )

    return _dedup(products, filepath.name)


def load_shopware_data(filepath: Path) -> list[ShopwareProduct]:
    """Load the Shopware product export. Expects fixed English column names:
    sku, product_name, brand, category, current_rrp, cost_price, active
    """
    encoding = _detect_encoding(filepath)
    with filepath.open(encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    products: list[ShopwareProduct] = []
    for row in rows:
        sku = row.get("sku", "").strip()
        if not sku:
            continue
        products.append(ShopwareProduct(
            sku=sku,
            product_name=row.get("product_name", "").strip(),
            brand=row.get("brand", "").strip(),
            category=row.get("category", "").strip(),
            current_rrp=_parse_price(row.get("current_rrp", "")),
            cost_price=_parse_price(row.get("cost_price", "")),
            active=_to_bool(row.get("active", "true")),
        ))

    return _dedup(products, filepath.name)
