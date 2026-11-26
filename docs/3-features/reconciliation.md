---
title: Reconciliation
status: current
updated: 2026-11-26
---

# Reconciliation

> A dataset-by-dataset comparison with DataCite's own `citationCount`, which catches a failed or incomplete DataCite harvest. `citations/reconcile.py`.

## Why it works

The DataCite source harvests the exact list behind every cited dataset's `citationCount` (`relationships.citations`). So a dataset whose harvested DataCite links fall short of its count points at a harvest that failed or was cut short, not at a difference of opinion.

Differences in what is *counted* are expected and explained by each link's class and status. For example DataCite counts links between datasets, which v4 publishes as `dataset-link` rather than counting them.

## What it gives

For every dataset that DataCite counts as cited, or that has a counted link here, one row of `Results/v4/reconciliation.csv`:

| Column | Meaning |
| --- | --- |
| `datacite_citation_count` | DataCite's `citationCount` |
| `datacite_links_harvested` | DataCite's citing works that were harvested |
| `missing_vs_datacite` | how many short of the count |
| `datacite_links_counted`, `_dataset_link`, `_excluded`, `_other_class` | how DataCite's links were classified here |
| `pipeline_counted` | counted links from every source |
| `pipeline_counted_not_in_datacite` | counted links DataCite doesn't have |
| `pipeline_all_links` | every link, counted or not |
| `complete` | `datacite_links_harvested` reaches the count |

A summary goes into `manifest.json` under `reconciliation`. Its `incomplete_share`, the share of DataCite-cited datasets that are not complete, is a guard: above 5% (`reconcile_threshold`) publishing is refused.

## Running it

```
python -m citations reconcile
```

prints the summary and the datasets furthest short of their count.
