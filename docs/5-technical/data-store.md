---
title: Data store
status: current
updated: 2026-11-26
---

# Data store

> The SQLite file that holds every stage's data between runs. Its schema is `SCHEMA` in `citations/db.py`. It replaces the pickles v3 committed in `Results/intermediate_data`.

The store is `data/citations.sqlite` by default (`--db`, or `CITATIONS_DB`). It is **not** committed: the weekly workflow carries it between runs in the Actions cache, and keeps a copy as a 30-day run artifact. If the cache is evicted, the next run builds a new store from scratch; it takes longer, and first-seen dates are seeded from the published `links.csv`.

## Runs and good runs

Every stage, and every source's harvest, records a row in `runs` when it starts and updates it when it finishes:

| Status | Meaning |
| --- | --- |
| `running` | started and not finished; if it stays so, the job was stopped, and a harvest will be resumed |
| `success` | finished and usable |
| `partial` | a harvest with too many failed requests (resumed next run), or a works stage with too many failed lookups |
| `failed` | raised an error |
| `rejected` | a harvest that lost too many links |
| `skipped` | a source that cannot run here (Overton with no key) |
| `blocked` | publishing refused by a guard |

`source_state` points each source, and the inventory, at its **good run**: the last one that succeeded. Later stages read only good runs' data. When a harvest succeeds, the raw links and fetch log of the source's older runs are deleted.

`runs.details` holds JSON with what else is worth keeping: counts of what a source dropped and why, `throttled_429`, an accepted drop, the guards' warnings.

## Tables

| Table | One row per | Written by |
| --- | --- | --- |
| `meta` | setting: `schema_version`, and `work_type_vocabulary` once types are mapped to Crossref's | `connect` |
| `runs` | stage or harvest run | every stage |
| `source_state` | source (and `inventory`): its good run, when it finished, and its rows | inventory, harvest |
| `datasets` | dataset in the current inventory | inventory |
| `dataset_relations` | `relatedIdentifiers` entry of a dataset | inventory |
| `datasets_new`, `dataset_relations_new` | staging tables, empty between runs | inventory |
| `raw_links` | link as one source reported it in one run, with the work's hint | harvest |
| `fetch_log` | key (usually a DOI) fetched in a harvest run, `ok` or `error`; what makes a harvest resumable | harvest |
| `works` | citing work: metadata, citation string, when each was fetched | works |
| `links` | classified link, as published | merge |
| `link_history` | link ever seen, with its first and last dates | merge |

Column comments in `SCHEMA` give each column's values.

## Looking inside

```
python -m citations status
```

or open the file with any SQLite client. For example, the latest harvest of each source:

```sql
SELECT source, run_id, status, rows, errors, message
FROM runs WHERE stage = 'harvest'
  AND run_id IN (SELECT MAX(run_id) FROM runs WHERE stage = 'harvest' GROUP BY source);
```

## Changing the schema

`CREATE TABLE IF NOT EXISTS` means a new table appears in existing stores by itself. A new column in an existing table does not: add an `ALTER TABLE` step to `connect`, guarded by a `meta` key the way `_crossref_work_types` is, so it runs once per store. The cached store in Actions is then upgraded on the next run.
