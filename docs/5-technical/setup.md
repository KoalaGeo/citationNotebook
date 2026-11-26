---
title: Setup
status: current
updated: 2026-11-26
---

# Setup

> Installing, configuring and running the pipeline.

## Install

Python 3.10 or later.

```
pip install -e ".[test]"         # the pipeline and pytest
pip install -e ".[notebook]"     # also pandas, matplotlib and JupyterLab, for inspect_results.ipynb
```

This installs the `citations` command; `python -m citations` does the same.

## Configure

| Setting | Where | Needed for |
| --- | --- | --- |
| `CITATIONS_MAILTO` | environment, or `--mailto` | a contact email for Crossref's and DataCite's polite pools, which allow more requests. Without it the lower anonymous limits are used |
| `OVERTON_API_KEY` | environment | Overton. Without it Overton is skipped (a warning, not a failure) |
| `CITATIONS_DB` | environment, or `--db` | the store; default `data/citations.sqlite` |
| `CITATIONS_WORKERS` | environment, or `--workers` | parallel requests per source; default 4 |

Never put a key in the code or in a committed file. In GitHub Actions they are a repository secret (`OVERTON_API_KEY`) and a variable (`CITATIONS_MAILTO`); see [Workflows](ci-cd-workflows.md).

Thresholds such as the publishing guards are fields of `Settings` in `citations/config.py`, each with its meaning in the class docstring.

## Run

```
python -m citations all          # the weekly run: every stage, then publish
python -m citations status       # the latest run of every stage, and what is in use
```

Stages can be run separately. Each one reads and writes the store at `data/citations.sqlite` (change it with `--db`); `--results` changes the results folder (default `Results`). The common options can go before or after the command.

| Command | Does |
| --- | --- |
| `inventory [--snapshot F] [--save-snapshot F]` | Every DOI of `bl.nerc`, checked against DataCite's total. `--snapshot` rebuilds from a saved download. |
| `harvest [datacite scholexplorer overton crossref] [--no-resume] [--accept-drop S …]` | Harvests the sources, all at the same time. A harvest that was interrupted or partial, and started in the last 8 days, resumes and retries only what failed, so the next weekly run picks it up. `--accept-drop`: see [Guards](../3-features/publishing-and-guards.md#guards). |
| `works` | Metadata and a plain-text citation string for each citing work, cached and refreshed every 90 days, and saved as it is fetched. |
| `merge` | One link per dataset × citing work from each source's latest good harvest, classified and filtered. |
| `publish [--force] [--no-v3] [--accept-drop S …]` | Writes `Results/v4` and `Results/v3` if the guards pass. `--force` publishes anyway and records that in the manifest. |
| `reconcile` | Compares each dataset with DataCite's `citationCount`. |
| `status` | The latest run of every stage and source, and each source's good run. |
| `all [--skip S …] [--force] [--no-resume] [--accept-drop S …] [--snapshot F] [--save-snapshot F]` | Every stage in order, then publish. |

Exit codes: 0 success, 1 a stage failed, 2 publishing was blocked by a guard. `all` returns 0 when it published, even if an optional stage failed; a warning says which.

A first run on an empty store fetches every citing work's metadata and citation string, so it takes much longer than later runs, which reuse what the store holds.

## Inspect

```
python -m citations status
sqlite3 data/citations.sqlite "SELECT stage, source, status, message FROM runs ORDER BY run_id DESC LIMIT 10"
```

The store's tables are described in [Data store](data-store.md). For the published results, use the [inspection notebook](../3-features/inspect-notebook.md).
