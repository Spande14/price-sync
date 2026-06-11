# price-sync

A CLI tool for synchronising supplier price lists with Shopware 6. Built for companies managing multiple brands, where suppliers periodically send updated cost prices and recommended retail prices (RRP) that need to be compared against current Shopware data before any changes are made.

## Background

A recurring operational challenge is that suppliers frequently send updated price lists containing both cost prices and RRPs. Two distinct systems are involved in acting on them:

- **Selling prices** are managed in the Shopware frontend and should be updated immediately when a new RRP is received.
- **Cost prices** live in the purchasing system and follow the *unit*, not the SKU. This means there is a window after a price list update where products may temporarily be sold at a different margin — the new RRP takes effect immediately, but the cost price only updates when the next batch of that SKU is purchased.

In this case all the data is managed in the same file which it should not be in a real world scenario. 

## How to run

**Install dependencies** (one-time):

```
pip install -r requirements.txt
```

**Each time you receive a new price list:**

1. Export current product data from Shopware and save it as `data/existing/shopware.csv` (fixed column format — see [Existing Shopware data])
2. Drop one or more supplier price list files into `data/input/` (CSV or xlsx, any filename)
3. Run:

```
python3 main.py
```

4. Open the timestamped report written to `output/` — auto-approved rows can be actioned immediately, everything else is flagged for manual review

Files that can't be recognised are skipped with a warning; the rest of the batch still runs. Warnings are printed to stdout.

## How it works

The script:
1. Loads all supplier files from `data/input/` (a file whose columns can't be recognised is skipped with a warning — it does not abort the run)
2. Pools every product from every file into one set, keyed by SKU
3. Compares new cost prices and RRPs against current Shopware data, matching on SKU
4. Calculates the current and new margin for each product
5. Flags what could be auto-approved based on margin rules (see [Auto-approval rules]); everything else is flagged for manual review
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

## Choices and trade-offs

**Margin direction as status, not price direction.** The output classifies each change as `margin_increase` or `margin_decrease` rather than `price_increase`, `price_decrease`, or `cost_change`. A cost increase and an RRP decrease both erode margin — the downstream consequence is the same regardless of which price moved, so the status reflects what the business actually cares about.

**Two-gate approval rather than a single threshold.** Approving purely on the new margin being above the minimum would silently pass a product that drops from 80% to 61% margin as long as 61% clears the floor. The hard 2 pp decline block catches these cases. The tradeoff is more manual reviews, but a false auto-approval is worse than an unnecessary manual review.

**CSV instead of API.** Shopware data is read from a static export rather than pulled live from the API. This keeps the tool self-contained and easy to run without credentials, but it means the comparison is only as fresh as the last export. In production this should be a live API call.

**Deterministic parsing instead of LLM.** An LLM could handle novel supplier formats and multilingual column headers without any code changes. The tradeoff is that supplier data is commercially sensitive, which would require self-hosted model infrastructure. The current alias-map approach works well across consistent formats, and extending it for a new supplier typically takes under a minute.

**SKU as the only match key.** Matching purely on SKU means brand is irrelevant to the comparison logic — a file can contain multiple brands, and a brand can be split across files. The tradeoff is that a SKU collision between two unrelated suppliers would silently overwrite one with the other but will create a warning in the terminal. In case there a many cases where more than one supplier can supply a SKU and we want to buy from both suppliers, then another identifer than SKU is needed to manage cost prices. 

**No discontinuation detection.** A Shopware SKU absent from the supplier input is simply ignored. Flagging absent SKUs as discontinued would require the input to be the full catalogue, which cannot be assumed.

## Scaling to more brands

The script itself is brand-agnostic by design — adding a new brand requires no code changes if the supplier's column names match existing aliases:

- Drop the new supplier file into `data/input/` and run as normal
- If the file uses new column names, add them to the alias map in `parser.py` — one line per alias
- Category thresholds in `auto_approve.py` are a dictionary; adding a new category minimum is one line
- New brands, product categories, and the related SKUs need to be present in the Shopware CSV

The only thing that does not scale automatically is if a new supplier uses a file format or encoding not yet handled (e.g. a fixed-width file). That would require a parser extension, not a configuration change.

## What I would not automate

**New products.** A SKU that exists in the supplier file but not in Shopware requires a human to set up the product — assign the correct category, write copy, configure variants. Auto-creating it risks miscategorisation, which would apply the wrong margin threshold to every future price update for that SKU.

**Large margin declines.** The 2 pp hard block is deliberately conservative. A change that pushes margin down 3 pp might be completely intentional (a promotional period, a strategic price match), but the tool has no way to know. These should always go to a person.

**Changes during an active purchasing cycle.** As described in the background: there is a window after an RRP update where the new selling price is live but the cost price in the purchasing system still reflects the old batch. Auto-approving a cost change during this window could produce a misleading margin calculation. In production, a check against open purchase orders would be needed before automating cost-driven changes.

**Borderline cases.** A new margin of exactly 62.1% against a 62% minimum passes the gate, but a human reviewer might reasonably hold it for context. The tool approves it — adding a buffer zone would require a business decision on where to draw the line.

## Production considerations

**API integration.** Replace the Shopware CSV export with a live call to the Shopware 6 API so comparisons are always against current data. Prices can change between the export and the run, which would produce stale baseline margins.
This also enables the script to write back to Shopware once price changes are approved. 

**CLI vs. GUI.** The current CLI works for very few people but an HTML based GUI can enable the majority of potential users. CLI works well for prototyping and was mentioned specifically in the case. A GUI would be preferred once we move to production.

**Audit trail.** Every auto-approved change should be logged with a timestamp, the operator identity, the before/after values, and the reason string. This matters for finance and compliance: if a margin drops below target after an auto-approval, you need to be able to reconstruct exactly what the tool saw and why it approved it.

**Input validation at the boundary.** The parser currently handles missing or unparseable prices by flagging them as `invalid_data`. In production, additional validation should be applied before the file enters the pipeline: file size limits, a check that the SKU count is within a plausible range of the previous run, and a checksum or signature if the supplier can provide one. A malformed or tampered file should be rejected before parsing, not discovered mid-run.

**Credentials and secrets.** Shopware API credentials, any supplier SFTP keys, and notification webhook URLs must not live in the codebase. Use environment variables or a secrets manager.

**Test coverage on real data.** The current test suite uses synthetic files that deliberately cover known edge cases in parsing and approval logic. Production robustness depends on how well real supplier files are represented. The first step after go-live should be building a regression suite from historical supplier files, with any parsing failures fed back into the alias map and number-format handling.

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
