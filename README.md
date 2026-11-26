# NERC EDS dataset citations

Harvests the links between NERC Environmental Data Service datasets (DataCite client `bl.nerc`) and the works that cite or relate to them, classifies each link, and publishes the results in `Results/v4`. The EDS citation API, the citation widget and the data centres' cited-data catalogues read them. A v3-compatible copy is still written to `Results/v3` while consumers move over.

This is not a census of every citation. It covers what DataCite, Scholexplorer, Overton and Crossref expose openly.

## Quick start

```bash
pip install -e ".[test]"
pytest                                       # offline, a few seconds

export CITATIONS_MAILTO=you@example.org      # contact email for the Crossref / DataCite polite pools
export OVERTON_API_KEY=...                   # optional; Overton is skipped without it
python -m citations all                      # the weekly run
python -m citations status                   # what ran and what is in use
```

Each stage can also be run on its own (`inventory`, `harvest`, `works`, `merge`, `publish`, `reconcile`); see [Setup](docs/5-technical/setup.md). Exit codes: 0 success, 1 a stage failed, 2 publishing was blocked by a guard.

## How it works

1. **Inventory**: every DOI of `bl.nerc`, checked against DataCite's own total.
2. **Harvest**: DataCite, Scholexplorer, Overton and Crossref, all at the same time, each within its API's rate limit. A failed or partial harvest never replaces the last good one.
3. **Works**: metadata and a plain-text citation string for every citing work, cached between runs.
4. **Merge**: one link per dataset and citing work, with every source that found it, a relation class and, if it breaks a rule, an exclusion reason.
5. **Publish**: if the guards pass, write `Results/v4` and `Results/v3`. If a required source failed, is stale or lost links, nothing is published and the previous results stay.

Everything between stages is kept in a SQLite store, `data/citations.sqlite`. See [Architecture](docs/1-vision/architecture.md).

## What it publishes

| File in `Results/v4` | One row per |
| --- | --- |
| `datasets.csv`, `datasets.json` | `bl.nerc` DOI, cited or not |
| `links.csv`, `links.jsonl` | dataset × citing work, excluded links included |
| `works.csv`, `works.json` | citing work |
| `reconciliation.csv` | dataset, compared with DataCite's `citationCount` |
| `manifest.json` | run: source status, counts, guard results and a hash of every file |

A link is **counted** when it is an included citation or supplement. Other links (documentation, versions, similar or related datasets) are published as related, never counted. Excluded links (comments, peer reviews, works much older than the dataset ...) are published with their reason, never deleted. See [Counting rules](docs/2-specification/counting-rules.md), [Results/v4](docs/2-specification/results-v4.md) and [Results/v3](docs/2-specification/results-v3.md).

`inspect_results.ipynb` validates and summarises the published results, and checks that `Results/v3` keeps the shape and types the EDS citation API needs. See [Inspection notebook](docs/3-features/inspect-notebook.md).

## The weekly run

`.github/workflows/citations.yml` runs every Sunday: tests, then `python -m citations all`, then it commits the results. A failed or blocked run opens an issue labelled `citations-pipeline`. It needs the secret `OVERTON_API_KEY` and the variable `CITATIONS_MAILTO`. See [Workflows](docs/5-technical/ci-cd-workflows.md).

## Project structure

```
├── citations/              the pipeline
│   ├── cli.py              the command line
│   ├── inventory.py        stage 1
│   ├── harvest.py          running a source harvest
│   ├── sources/            datacite, scholexplorer, overton, crossref
│   ├── works.py            stage 3, with citation_text.py and worktypes.py
│   ├── merge.py            stage 4, with ids.py, relations.py and filters.py
│   ├── publish.py          stage 5, with guards.py and reconcile.py
│   ├── http.py             retries and rate limits
│   └── db.py               the SQLite store
├── tests/                  offline tests: a fake HTTP layer stands in for every API
├── Results/v4, v3          the published results (v1 and v2 are no longer updated)
├── inspect_results.ipynb   validation and overview of the results
└── docs/                   the documentation
```

## Development

```bash
pytest
```

`.github/workflows/tests.yml` runs the tests on Python 3.10 and 3.12 for every pull request and every push to `main`. Every module, class and function has a Google-style docstring. Read [AGENTS.md](AGENTS.md) before changing the code.

## Documentation

| Section | |
| --- | --- |
| [1-vision](docs/1-vision/) | [Principles](docs/1-vision/principles.md), [architecture](docs/1-vision/architecture.md), [use cases](docs/1-vision/use-cases.md) |
| [2-specification](docs/2-specification/) | [Counting rules](docs/2-specification/counting-rules.md), [Results/v4](docs/2-specification/results-v4.md), [Results/v3](docs/2-specification/results-v3.md) |
| [3-features](docs/3-features/) | What each stage does: [overview](docs/3-features/README.md) |
| [4-roadmap](docs/4-roadmap/) | [Changelog](docs/4-roadmap/CHANGELOG.md) (including what changed from v3), [current status](docs/4-roadmap/current.md), [backlog](docs/4-roadmap/backlog.md) |
| [5-technical](docs/5-technical/) | [Setup](docs/5-technical/setup.md), [workflows](docs/5-technical/ci-cd-workflows.md), [rate limits](docs/5-technical/performance-and-rate-limits.md), [data store](docs/5-technical/data-store.md), [testing](docs/5-technical/testing.md), [conventions](docs/5-technical/documentation.md) |

Start at [docs/README.md](docs/README.md).

## Authors

Matthew Nichols (UKCEH) wrote the original pipeline. The Crossref functions were adapted from the demo notebooks in the Crossref [rest-api-doc](https://github.com/CrossRef/rest-api-doc) repository.