# price-sync

A CLI tool for synchronising supplier price lists with Shopware 6. Built for companies managing multiple brands, where suppliers periodically send updated cost prices and recommended retail prices (RRP) that need to be compared against current Shopware data before any changes are made.

## Background

A recurring operational challenge is that suppliers frequently send updated price lists containing both cost prices and RRPs. Two distinct systems are involved in acting on them:

- **Selling prices** are managed in the Shopware frontend and should be updated immediately when a new RRP is received.
- **Cost prices** live in the purchasing system and follow the *unit*, not the SKU. This means there is a window after a price list update where products may temporarily be sold at a different margin — the new RRP takes effect immediately, but the cost price only updates when the next batch of that SKU is purchased.

In this case all the data is managed in the same file which it should not be in a real world scenario. 

## How it works

Place one or more supplier price list(s) in `data/input/` and run the main.py script. It must be .csv or xlxs. files

The script:
1. Loads all supplier files from `data/input/` (a file whose columns can't be recognised is skipped with a warning — it does not abort the run)
2. Pools every product from every file into one set, keyed by SKU
3. Compares new cost prices and RRPs against current Shopware data, matching on SKU
4. Calculates the current and new margin for each product
5. Flags what could be auto-approved based on margin rules (see [Auto-approval rules]; everything else is flagged for manual review
6. Writes a single combined CSV report to `output/`

### SKU-level matching

All comparison is done on the SKU. 
A single file may contain multiple brands, and a brand may be split across files. Each supplier row is matched to the Shopware row with the same SKU.

Because SKUs are global, if the same SKU appears in more than one input file the last occurrence wins and a warning names the conflict.

### Input file flexibility

Supplier files vary significantly in format. The parser handles:

- **CSV and xlsx** file formats
- **Encoding detection** — utf-8 (with or without BOM), latin-1, cp1252
- **Delimiter detection** — comma or semicolon
- **Metadata rows** — the header row is detected by scanning for known column name patterns, skipping any export metadata above it
- **Column name aliases** — a set of known aliases maps supplier-specific column names to canonical fields (e.g. `Cost Price (EUR)`, `Wholesale Price`, `buy_price` all map to `cost_price`)
- **Number formats** — English (`1,234.56`), European (`1.234,56`), Nordic space-separated (`1 234,56`), with or without currency symbols
- **Duplicate SKUs** — last occurrence kept, warning printed
- **Missing or unparseable prices** — a row with a blank or non-numeric cost/RRP is flagged as `invalid_data`, and routed to manual review with a warning, so bad data can never produce a false auto-approval
- **Unrecognised files** — if a file's required columns can't be mapped at all, that one file is skipped (with a warning) and the rest of the batch still runs

If a new supplier file uses column names not yet in the alias map, adding them is a one-line change.

### Existing Shopware data

```
sku, product_name, brand, category, active, cost_price, current_rrp
```

`category` drives the auto-approval thresholds, so it must be populated for the matching SKUs. `brand` is informational only — it is carried into the report but plays no part in matching.

### Output

A single CSV file per run: `output/combined_YYYY-MM-DD_HHMMSSZ.csv`

The timestamp is UTC (the trailing `Z`) and logs exactly when the price update was processed.

| Column | Description |
| --- | --- |
| `sku` | Product identifier |
| `brand` | Brand name from the matched Shopware row (empty for new products) |
| `category` | Product category from the matched Shopware row (empty for new products) |
| `product_name` | Product name from Shopware |
| `status` | `margin_increase`, `margin_decrease`, `unchanged`, `new_product`, `invalid_data` |
| `current_cost_price` | Cost price currently in Shopware |
| `new_cost_price` | Cost price from the new supplier price list |
| `current_rrp` | Current RRP in Shopware |
| `new_rrp` | RRP from the new supplier price list |
| `current_margin_pct` | Margin at current RRP and current cost |
| `new_margin_pct` | Margin at new RRP and new cost |
| `auto_approved` | Whether the change can be auto-approved |
| `reason` | Explanation of the approval decision |

The `status` values:

- `margin_increase` — new margin is higher than the current margin (RRP rose, cost fell, or both)
- `margin_decrease` — new margin is lower than the current margin (RRP fell, cost rose, or both)
- `unchanged` — both RRP and cost identical
- `new_product` — SKU in a supplier file but not in Shopware
- `invalid_data` — supplier row has a missing or unparseable price; always routed to manual review

Only SKUs that appear in the supplier input are reported. A Shopware SKU absent from the input is ignored

## File structure

```
data/
  input/           # Drop supplier price lists here (any filename)
  existing/
    shopware.csv   # Shopware product export
output/            # Combined CSV reports written here
src/
  parser.py        # File loading, column mapping, number parsing
  comparator.py    # SKU matching and margin calculations
  auto_approve.py  # Approval rules per category
  reporter.py      # CSV writer
main.py
tests/             # Unit tests (stdlib unittest, no extra deps)
requirements.txt
```

## Auto-approval rules

A `margin_increase` or `margin_decrease` is auto-approved only when **both** gates pass:

1. **Margin must not decline by 2 percentage points or more.** Any drop of ≥2 pp versus the current margin is blocked outright, regardless of how healthy the resulting margin is.
2. **The new margin must still meet the category minimum** (no buffer).

Thresholds are set per product category:

| Category | Minimum margin |
| --- | --- |
| Fragrance | 62% |
| Skincare | 64% |
| Wellness | 65% |
| *(all others)* | 50% |

`new_product` and `invalid_data` always require manual review.

## Limitations and design decisions

**CSV instead of API.** Shopware data is read from a CSV export rather than pulled live from the Shopware 6 API. In production this would ideally be a direct API call to ensure the comparison is always against current data.

**No discontinuation detection.** The tool only reports on SKUs present in the supplier input. A Shopware SKU missing from the input is not flagged — unpublishing discontinued products is out of scope, since the input is not assumed to be the full catalogue.

**Deterministic script vs. LLM parsing.** There is a reasonable argument for using an LLM to parse and map supplier price lists — format variation across suppliers is significant, and an LLM could handle ambiguous or novel layouts without code changes. An additional advantage is that LLMs handle multilingual input naturally: a supplier sending column headers in German, French, or Danish requires no alias additions — the model translates and maps on the fly. The tradeoff is that supplier data is commercially sensitive, which would require self-hosted model infrastructure. The current Python approach works well when there is enough consistency across supplier formats. In practice, when a new supplier file does not parse correctly, debugging and extending the alias map typically takes under a minute with use of claude code.

**Built on dummy data.** The tool was developed against three synthetic supplier files (one per brand, in `data/input/`) that deliberately differ in column names, delimiters, currencies, and number formats, plus a unit-test suite covering the parsing and approval logic. Production robustness will depend on how closely real supplier files match the patterns covered by the alias map, and will improve as it is built on historical data.

## Requirements

```
openpyxl>=3.0
```

```
pip install -r requirements.txt
```

## Tests

```
python3 -m unittest discover -s tests
```

Tests use the standard-library `unittest` — no extra dependencies. They cover the two highest-risk areas: price parsing (unparseable input must never collapse to `0.0`) and the approval policy (both gates, boundary cases at exactly the threshold and exactly −2 pp).
