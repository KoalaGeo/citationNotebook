---
title: Current status
status: current
updated: 2026-11-26
---

# Current status

> Where the v4 pipeline stands.

## Done ✅

- The v4 pipeline (`citations` package) replaces the v3 notebooks: inventory, four sources, works, merge, publish, guards and reconciliation.
- The weekly workflow publishes `Results/v4`, and `Results/v3` in the v3 pipeline's exact format for the EDS citation API.
- The inspection notebook validates both, and checks the v3 files against upstream's.
- Docstrings and these docs.

## In progress 🔄

- **Merging v4 upstream.** The v4 pipeline is proposed to [NERC-EDS/citationNotebook](https://github.com/NERC-EDS/citationNotebook) in [NERC-EDS/citationNotebook#36](https://github.com/NERC-EDS/citationNotebook/pull/36), from this fork's `main`. Until it is merged, upstream's own weekly notebook runs keep changing the same result files, so the pull request needs upstream's `main` merged in after each run.

## Next 📋

See the [backlog](backlog.md). The first items are merging preprints with their published articles, and moving the EDS citation API to `Results/v4` so `Results/v3` can be retired.
