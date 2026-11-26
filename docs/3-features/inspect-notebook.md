---
title: Inspection notebook
status: current
updated: 2026-11-26
---

# Inspection notebook

> `inspect_results.ipynb` validates and summarises what has been published. It reads the result files only and calls no citation API.

## Running it

```
pip install -e ".[notebook]"
jupyter lab inspect_results.ipynb
```

In the **Settings** cell choose the results to inspect: a local `Results` folder, or this repository on GitHub at a branch, tag or commit. Optionally choose a second version to compare with, and the upstream repository and ref for the v3 format check (`UPSTREAM_REPO`, `UPSTREAM_REF`).

## What it does

**Part 1: Validation.** Each check reports PASS, WARN, FAIL or INFO, and the failing rows are written to `inspect_outputs/`.

- **1a. v4**: the files against the [Results/v4 format](../2-specification/results-v4.md), their integrity, the counting rules, the manifest and the reconciliation.
- **1b. v3**: CSV and JSON agree, data quality, and, when v4 is present, that v3 holds exactly v4's counted links.
- **1c. v3 file formats against upstream**: the v3 files keep the shape and types of upstream's, which the EDS citation API reads: the same columns in the same order, the same encoding, and no kind of value a column or JSON field has never had upstream. The full comparison is written to `inspect_outputs/v3_schema_vs_upstream.csv`. Run this after any change to how v3 is written.

**Part 2: Overview.** Counted citations and related links by data centre (2a); where counted citations come from and how often sources agree (2b); exclusions (2c); metadata completeness of counted citing works (2d); the most-cited datasets (2e); citations by calendar year and UK fiscal year (2f); links new since a date (2g).

**Part 3: One dataset.** `show_dataset(doi)`: every link, its sources, class, status and citing work.

**Part 4: Compare with another version.** Per-dataset changes, and `compare_dataset(doi)` for new, gone and unchanged citing works. A legacy v3 version is classified with the v4 rules first, so counts compare like for like.
