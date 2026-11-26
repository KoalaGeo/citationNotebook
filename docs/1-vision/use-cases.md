---
title: Use cases
status: current
updated: 2026-11-26
---

# Use cases

> Who reads the results, and what each of them needs from them.

## EDS citation API

**Reads:** `Results/v3/latest_results.csv` and `latest_results.json`, from GitHub.

**Needs:** the files to keep exactly the shape and types the v3 pipeline wrote: the same columns in the same order, the same encodings, a float `data_publication_year`, and v3's placeholder text instead of empty values. If any of that changes, the API stops working.

**How the pipeline meets it:** `Results/v3` is built from v4 data in v3's format ([Results/v3](../2-specification/results-v3.md)). Section 1c of `inspect_results.ipynb` compares the files with upstream's, column by column.

**Next:** move the API to `Results/v4`, then stop writing `Results/v3` (see the [backlog](../4-roadmap/backlog.md)).

## The citation widget and data-centre catalogues

The widget on dataset landing pages, and the data centres' cited-data catalogues, show a dataset's citations.

**Needs:** a count that only includes real citations, a readable citation string for each citing work, and the other links shown separately as *related datasets and documents*.

**How the pipeline meets it:** `counted` marks included citations and supplements; every other link has its `relation_class`. Every citing work has a plain-text `citation_text`: a formatted citation, else one built from its metadata, else a link to it. See [Counting rules](../2-specification/counting-rules.md).

## Reporting

EDS reports how often its datasets are cited: in all, by data centre, and by UK fiscal year.

**Needs:** stable, comparable counts with known rules, and dates that can be trusted.

**How the pipeline meets it:** each link's `first_seen` date, each work's `issued` date with its precision, and per-dataset counts in `datasets.csv`. Part 2 of the inspection notebook produces these summaries, including citations by UK fiscal year (section 2f) and links new since a date (2g).

## Checking one dataset

A data centre asks why a dataset shows the citations it does, or why one is missing.

**How the pipeline meets it:** `links.csv` lists every link for the dataset with its sources, raw relations, class, status and exclusion reason. In the notebook, `show_dataset(doi)` shows it all in one place; `reconciliation.csv` shows how the dataset's DataCite `citationCount` compares.

## Comparing two runs

Before and after a code change, or week to week.

**How the pipeline meets it:** Part 4 of the notebook compares two versions of the results (a folder, or the repository at a branch, tag or commit) per dataset, and `compare_dataset(doi)` lists new, gone and unchanged citing works. A v3 version is classified with the v4 rules first, so counts compare like for like.

## Running it unattended

The pipeline runs every Sunday on GitHub Actions with nobody watching.

**Needs:** a broken source must not quietly publish bad results; someone must hear about it; an interrupted run must not lose a week's work.

**How the pipeline meets it:** the [guards](../3-features/publishing-and-guards.md) block publishing and the workflow opens an issue labelled `citations-pipeline`. Harvests resume, and works are saved as they arrive. See [Workflows](../5-technical/ci-cd-workflows.md).
