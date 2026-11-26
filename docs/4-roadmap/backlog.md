---
title: Backlog
status: current
updated: 2026-11-26
---

# Backlog

> Planned and possible work, highest priority first.

| # | Item | Priority | Status |
| --- | --- | --- | --- |
| 1 | Merge a preprint with its published article | High | 📋 |
| 2 | Move the EDS citation API to `Results/v4`, then retire `Results/v3` | High | 📋 |
| 3 | Rotate the old Overton API key | High | 📋 |
| 4 | Merge other duplicate identifiers for one work | Medium | 📋 |
| 5 | Fewer Scholexplorer requests | Low | 💡 |
| 6 | Publish these docs as a site | Low | 💡 |
| 7 | Remove the unused `PublishBlocked` exception | Low | 📋 |

Status: 📋 planned, 💡 idea.

## 1. Merge a preprint with its published article

About 370 counted links in the October 2026 results are a preprint and the article it became, both linked to the same dataset. Link the two with Crossref's `is-preprint-of` relation, falling back to a matching title and first author within one dataset; count the published version and publish the preprint link as excluded with its own reason; keep counting a preprint with no published version. See [Known limitations](../2-specification/counting-rules.md#known-limitations).

Affects: a new `exclusion_reason`, `merge.py`, the counting rules, and every consumer's counts.

## 2. Move the EDS citation API to `Results/v4`, then retire `Results/v3`

`Results/v3` exists only because the EDS citation API reads it. Once the API reads `Results/v4`, stop writing v3 (`publish --no-v3`, or `write_v3 = False`), drop section 1c of the notebook, and remove the v3 code in `publish.py`.

## 3. Rotate the old Overton API key

v3 had the Overton key in its code, so it is in the git history. The v4 pipeline reads a new key from the `OVERTON_API_KEY` secret; the old one should be revoked.

## 4. Merge other duplicate identifiers for one work

About 85 counted links are a DOI and the same work as an OpenAIRE or repository URL, and about 20 are version DOIs of one Zenodo or figshare record.

## 5. Fewer Scholexplorer requests

Scholexplorer is queried once per dataset (6,000+ requests). Try querying by target publisher instead, and check it returns the same links before switching.

## 6. Publish these docs as a site

The docstrings are ready for mkdocstrings. See [Documentation](../5-technical/documentation.md) for a tested configuration.

## 7. Remove the unused `PublishBlocked` exception

`citations/publish.py` defines `PublishBlocked` but nothing raises it: `run_publish` returns `"blocked"`. Remove it, or raise it from `run_publish` and catch it in the CLI.
