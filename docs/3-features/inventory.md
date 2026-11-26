---
title: Inventory
status: current
updated: 2026-11-26
---

# Inventory

> Every DOI registered to the DataCite client `bl.nerc`, checked against DataCite's own total. Every other stage works from this list.

## How it works

1. Pages through `https://api.datacite.org/dois?client-id=bl.nerc` by **cursor**, 1,000 records a page, with `affiliation` and `publisher` switched on. Cursor paging has no 10,000-record limit and skips no pages.
2. Parses each record into a `datasets` row (DOI, publisher, data centre, title, year, resource type, registration date, authors with ORCID iDs, DataCite's `citationCount`) and its `relatedIdentifiers` into `dataset_relations`.
3. Drops repeated records of the same DOI (and counts them).
4. **Checks the count.** If the number of unique DOIs is not the total DataCite reported, the run fails and the previous inventory stays in use.
5. Replaces both tables in one transaction and makes this the inventory's good run.

The data centre comes from the DataCite publisher name, with the v3 pipeline's keyword rules (`data_centre` in `citations/config.py`): "polar" is PDC; "atmospheric", "badc" or "earth" is CEDA; "oceanographic" is BODC; "geological" or "geoscience" is NGDC; "environmental information" is EIDC; "environmental data" is CEDA.

## Snapshots

`--save-snapshot FILE` saves the downloaded records (gzipped JSON); `--snapshot FILE` rebuilds the inventory from one without calling DataCite. The weekly workflow saves one as a run artifact for 30 days, so an inventory can be re-examined later.

## If it fails

`python -m citations all` carries on with the last good inventory if there is one (and annotates the run); with none it stops. The run's message says why, for example `InventoryIncomplete: 6396 unique DOIs retrieved but DataCite reports 6397; not replacing the inventory.`

## Tests

`test_incomplete_inventory_is_not_used` (a short count fails and keeps the old inventory) and `test_full_run` (cursor paging, a repeated record) in `tests/test_pipeline.py`.

## v3

v3 used page-number paging with no completeness check: in October 2026 12 DOIs were missing and 10 duplicated.
