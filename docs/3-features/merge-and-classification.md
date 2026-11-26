---
title: Merge and classification
status: current
updated: 2026-11-26
---

# Merge and classification

> Raw links from every source's good harvest become one classified link per dataset and citing work. `citations/merge.py`, with the rules in `citations/relations.py` and `citations/filters.py`.

## How it works

1. Reads the raw links of each source's **good run** only. Raw links for DOIs no longer in the inventory are dropped and counted (`orphaned_raw_links`).
2. Groups them by `(data_doi, citing_id)`. Identifiers were normalised at harvest, so the same work from two sources is one group.
3. Picks the group's relation: the one with the highest-priority class (citation, supplement, documentation, other, version-or-part, similarity), alphabetically on a tie.
4. A link of a "use" class (citation, supplement, documentation, other) to another NERC dataset becomes `dataset-link`.
5. Applies the exclusion rules, using the citing work's metadata and the dataset's year.
6. Sets `counted` for included citations and supplements.
7. Lists every source that found the link in `sources`, and each one's raw relations in `source_relations`.
8. Takes `first_seen` from `link_history`, or today for a new link; sets `last_seen` to today.
9. Replaces the `links` table and updates `link_history` in one transaction.

The rules themselves are in [Counting rules](../2-specification/counting-rules.md).

## First-seen dates on a fresh store

When `link_history` is empty (a new store, or the Actions cache was evicted), it is seeded from `Results/v4/links.csv`, or, before v4 was first published, from `date_added` in `Results/v3/latest_results.csv`. Links keep the date they were first found.

## Changing a rule

- A relation's class: `CLASS_OF` in `citations/relations.py`. Which classes are counted: `COUNTED_CLASSES`.
- Exclusion rules: `exclusion_reason` in `citations/filters.py`. Add a new reason to `REASONS` too.
- The pre-dates tolerance: `predates_tolerance_years` in `Settings`.

Then update [Counting rules](../2-specification/counting-rules.md) and the README, add a changelog entry, and check the effect on real results with the notebook's comparison (Part 4). A change to counting changes every consumer's numbers.

## Tests

`tests/test_ids_relations_filters.py` (identifiers, relations, classes and every exclusion rule) and `test_full_run` and `test_first_seen_survives_and_seeds_from_v3` in `tests/test_pipeline.py`.
