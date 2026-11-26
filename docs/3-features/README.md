---
title: Features overview
status: current
updated: 2026-11-26
---

# Features overview

> What each stage does, the settings that change it, where its code is and which tests cover it.

| Feature | Status | Page | Code |
| --- | --- | --- | --- |
| Inventory of every `bl.nerc` DOI, checked against DataCite's total | ✅ | [Inventory](inventory.md) | `citations/inventory.py` |
| DataCite: the citations DataCite counts, and relations in dataset metadata | ✅ | [Sources](sources.md#datacite) | `citations/sources/datacite.py` |
| Scholexplorer: every incoming Scholix link, with its relation kept | ✅ | [Sources](sources.md#scholexplorer) | `citations/sources/scholexplorer.py` |
| Overton: policy documents, every dataset each one cites | ✅ | [Sources](sources.md#overton) | `citations/sources/overton.py` |
| Crossref data citations (beta endpoint) | ✅ | [Sources](sources.md#crossref) | `citations/sources/crossref.py` |
| Resumable harvests, error-rate and row-drop checks | ✅ | [Sources](sources.md#how-a-harvest-runs) | `citations/harvest.py` |
| Citing-work metadata, one work-type vocabulary, plain-text citation strings | ✅ | [Works and citation strings](works-and-citations.md) | `citations/works.py`, `citation_text.py`, `worktypes.py` |
| One classified link per dataset and citing work, with exclusions | ✅ | [Merge and classification](merge-and-classification.md) | `citations/merge.py`, `relations.py`, `filters.py`, `ids.py` |
| Guards before publishing; v4 and v3-compatible results; manifest with file hashes | ✅ | [Publishing and guards](publishing-and-guards.md) | `citations/publish.py`, `guards.py` |
| Reconciliation with DataCite's `citationCount` | ✅ | [Reconciliation](reconciliation.md) | `citations/reconcile.py` |
| Validation, overview and comparison notebook | ✅ | [Inspection notebook](inspect-notebook.md) | `inspect_results.ipynb` |
| Merging a preprint with its published article | 📋 | [Backlog](../4-roadmap/backlog.md) | |

Status: ✅ complete, 🔄 in progress, 📋 planned.

## The order things happen in

1. **Inventory**: every dataset DOI and its metadata.
2. **Harvest**: the four sources at the same time. Each stores raw links, one row per link as the source reported it.
3. **Works**: metadata and a citation string for every citing work.
4. **Merge**: raw links from each source's good harvest become one classified link per dataset and citing work.
5. **Publish**: the guards check the run, then the results are written.

Reconciliation runs inside publishing (its summary is a guard) and on its own with `python -m citations reconcile`.
