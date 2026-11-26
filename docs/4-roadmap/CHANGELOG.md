---
title: Changelog
status: current
updated: 2026-11-26
---

# Changelog

> Notable changes, newest first. The package version stays 4.0.0 until the v4 pipeline is merged upstream; changes since are listed by date and pull request.

## Unreleased

- Every module, class and function in `citations/` has a Google-style docstring (Args, Returns, Raises), ready for mkdocstrings; every test says what it checks.
- `docs/`: these pages. The README is now a short landing page that links to them.
- `AGENTS.md`: a guide for anyone (person or tool) changing the code.

No change in behaviour.

## 12 November 2026: v3 files keep the v3 pipeline's types

[KoalaGeo/citationNotebook#11](https://github.com/KoalaGeo/citationNotebook/pull/11). The EDS citation API reads `Results/v3`, so its files now keep v3's types exactly: a float `data_publication_year`, v3's placeholder text instead of empty values, the BOM on `latest_results.csv` only, and the JSON on one line. Dates stay unpadded.

## 26 October 2026: EGUsphere preprints counted

[KoalaGeo/citationNotebook#10](https://github.com/KoalaGeo/citationNotebook/pull/10). EGUsphere preprints are counted like any other preprint; only EGU General Assembly abstracts (`10.5194/egusphere-egu...`) are excluded as conference abstracts. v3 excluded every EGUsphere DOI.

## 22 October 2026: v3 format check in the notebook

[KoalaGeo/citationNotebook#9](https://github.com/KoalaGeo/citationNotebook/pull/9). Section 1c of `inspect_results.ipynb` compares the v3 files' shape and types with upstream's.

## 14 October 2026: faster weekly run

- [KoalaGeo/citationNotebook#7](https://github.com/KoalaGeo/citationNotebook/pull/7): the four sources are harvested at the same time; citation strings are fetched in parallel; every request is paced to its API's published rate limit; rate-limited (429) responses are counted.
- [KoalaGeo/citationNotebook#8](https://github.com/KoalaGeo/citationNotebook/pull/8): each source logs its progress every minute while harvesting.

## 14 October 2026: tidy

[KoalaGeo/citationNotebook#6](https://github.com/KoalaGeo/citationNotebook/pull/6). One work-type vocabulary, Crossref's, for every source; a link to the work as its citation when nothing else can be built; the `tests.yml` workflow, so tests run on every pull request; `harvest` before any inventory prints one line and exits 1 instead of a traceback.

## 13 October 2026: review fixes

[KoalaGeo/citationNotebook#5](https://github.com/KoalaGeo/citationNotebook/pull/5). `--accept-drop SOURCE` (and the workflow's `accept_drop` input) for a drop in links that is real; a failed metadata lookup is retried on the next run rather than after 90 days; the resume window is 8 days, so the next weekly run resumes an unfinished harvest; `harvest` with no sources works on Python 3.10 and 3.11; `inspect_outputs/` is no longer committed.

## 12 October 2026: 4.0.0, the `citations` package

[KoalaGeo/citationNotebook#4](https://github.com/KoalaGeo/citationNotebook/pull/4). The five v3 notebooks, five scheduled workflows and committed pickles are replaced by one Python package, one command, one workflow and a SQLite store. A review in October 2026 found gaps in v3 that had built up unnoticed:

v3 was five notebooks run by five scheduled workflows, with pickles committed between stages. A review in October 2026 found gaps that had built up unnoticed. Version 4 replaces the notebooks with a `citations` package, one CLI, one workflow and a SQLite store.

| v3 problem | v4 |
| --- | --- |
| The DataCite stage asked only for `is-cited-by`, `is-referenced-by` and `is-supplement-to` with the dataset as subject. It never saw citations from journal reference lists, which Crossref deposits as `references` events with the article as subject. These were 99% of the DataCite links missing from v3. | Harvests the exact list behind DataCite's `citationCount` for every cited dataset, labelled from its events. It also reads incoming relations from the datasets' own `relatedIdentifiers`. |
| Scholexplorer similarity recommendations (`HasAmongTopNSimilarDocuments`) were counted as citations: 44% of v3 rows. | Every link has a `relation_class`. Similarity and dataset-to-dataset links are published as related links and never counted. |
| Overton read only the first dataset each policy document cites. Its API key was in the code. | Every highlight is used. The key comes from the `OVERTON_API_KEY` secret (**rotate the old key**: it is in the git history). |
| The inventory used page-number paging with no completeness check: 12 DOIs were missing and 10 were duplicated. | Cursor paging, de-duplication, and the run fails if the count differs from DataCite's total. |
| Links were deleted by filters, and before Sept 2026 some were dropped without a record. Publication dates were the DOI registration date, written as D/M/YYYY. The pre-dates rule used a one-year cut. | Exclusions are kept with a `status` and `exclusion_reason`. Dates are the `issued` date in ISO 8601, with their precision. The pre-dates rule needs a gap of **two years or more**. |
| Each stage committed whatever it produced; an empty Scholexplorer harvest was published for 8 months. | A harvest only replaces the previous one when it succeeds. Publishing is refused when a required source failed, is stale or lost rows, and an issue is opened. |
| De-duplication used raw strings, so URL case variants survived, and only the first source was credited. | Identifiers are normalised and every source that found a link is listed. |

## Before v4

- 30 September 2026, [KoalaGeo/citationNotebook#3](https://github.com/KoalaGeo/citationNotebook/pull/3): repository tidy and README update.
- 29 September 2026, [KoalaGeo/citationNotebook#2](https://github.com/KoalaGeo/citationNotebook/pull/2): fixed the Scholexplorer workflow crash on citing works without a DOI.
- 27 July 2026, [KoalaGeo/citationNotebook#1](https://github.com/KoalaGeo/citationNotebook/pull/1): Scholexplorer moved to the Scholix v3 API.
