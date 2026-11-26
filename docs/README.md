---
title: Documentation
status: current
updated: 2026-11-26
---

# NERC EDS dataset citations: documentation

> Harvests the links between NERC Environmental Data Service datasets and the works that cite or relate to them, classifies each link, and publishes the results as CSV and JSON.

The [project README](../README.md) is the short version: what changed from v3, how to run it, and the output formats. These pages go into more depth, one subject per page.

## Quick links

| I want to... | Go to |
| --- | --- |
| Understand what the pipeline is for | [Use cases](1-vision/use-cases.md) |
| Understand the design decisions | [Principles](1-vision/principles.md) |
| See how the parts fit together | [Architecture](1-vision/architecture.md) |
| Know what is counted as a citation | [Counting rules](2-specification/counting-rules.md) |
| Read or consume the results | [Results/v4](2-specification/results-v4.md), [Results/v3](2-specification/results-v3.md) |
| See what each stage does | [Features overview](3-features/README.md) |
| See what has changed | [Changelog](4-roadmap/CHANGELOG.md) |
| See what is planned | [Current status](4-roadmap/current.md), [Backlog](4-roadmap/backlog.md) |
| Run it or develop it | [Setup](5-technical/setup.md) |
| Change the code | [Code and documentation conventions](5-technical/documentation.md), and [AGENTS.md](../AGENTS.md) |

## Documentation structure

| Section | Purpose | Key documents |
| --- | --- | --- |
| [1-vision/](1-vision/) | Why it exists and how it is designed | [Principles](1-vision/principles.md), [Architecture](1-vision/architecture.md), [Use cases](1-vision/use-cases.md) |
| [2-specification/](2-specification/) | What the outputs mean and contain. Consumers rely on these | [Counting rules](2-specification/counting-rules.md), [Results/v4](2-specification/results-v4.md), [Results/v3](2-specification/results-v3.md) |
| [3-features/](3-features/) | What each stage does, its settings and its tests | [Overview](3-features/README.md) |
| [4-roadmap/](4-roadmap/) | What has changed and what is next | [Changelog](4-roadmap/CHANGELOG.md), [Current](4-roadmap/current.md), [Backlog](4-roadmap/backlog.md) |
| [5-technical/](5-technical/) | Running, testing and maintaining it | [Setup](5-technical/setup.md), [Workflows](5-technical/ci-cd-workflows.md), [Rate limits](5-technical/performance-and-rate-limits.md), [Data store](5-technical/data-store.md), [Testing](5-technical/testing.md), [Documentation](5-technical/documentation.md) |

## Key concepts

| Concept | Meaning |
| --- | --- |
| **Dataset** | A DOI registered to the DataCite client `bl.nerc`. The inventory lists them all, cited or not. |
| **Citing work** | Anything linked to a dataset: an article, preprint, report, policy document, web page or another dataset. Identified by a DOI where it has one, else a URL, PubMed, PubMed Central or Handle identifier. |
| **Link** | One dataset and one citing work, with every source that reported it. |
| **Relation class** | What kind of link it is: `citation`, `supplement`, `documentation`, `other`, `dataset-link`, `version-or-part` or `similarity`. Only included citations and supplements are **counted**. |
| **Excluded link** | A link that breaks an exclusion rule (a comment, a peer review, a work older than the dataset ...). It is published with its reason, never deleted. |
| **Source** | An API the links come from: DataCite, Scholexplorer, Overton and Crossref. |
| **Run** | One stage, or one source's harvest, recorded in the store with its status. |
| **Good run** | A source's last successful harvest. Only a good run's links are used, so a failed harvest never replaces good data. |
| **Guard** | A check before publishing. A failed guard blocks publishing and keeps the previous results. |
| **Store** | The SQLite file (`data/citations.sqlite`) that holds every stage's data between runs. |

## Tech stack

| Part | Technology |
| --- | --- |
| Language | Python 3.10 or later |
| Dependencies | `requests` and `urllib3` only. `pandas` and `matplotlib` are used by the inspection notebook, not the pipeline |
| Working store | SQLite, carried between runs in the GitHub Actions cache |
| Outputs | CSV, JSON and JSON Lines, committed to `Results/` |
| Scheduling | GitHub Actions, every Sunday |
| Tests | `pytest`, offline: a fake HTTP layer stands in for every API |
| Docstrings | Google style, ready for [mkdocstrings](5-technical/documentation.md) |

## Getting started

```
pip install -e ".[test]"
pytest                                   # offline, a few seconds
export CITATIONS_MAILTO=you@example.org  # contact email for the polite rate limits
python -m citations all                  # the weekly run
python -m citations status               # what ran and what is in use
```

See [Setup](5-technical/setup.md) for the details.
