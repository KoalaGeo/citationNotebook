---
title: Publishing and guards
status: current
updated: 2026-11-26
---

# Publishing and guards

> The checks a run must pass before anything is published, and how the results are written. `citations/guards.py` and `citations/publish.py`.

## Guards

Publishing is refused (exit code 2, previous results kept, an issue opened by the workflow) when any of these is true:

- the inventory, DataCite or Scholexplorer has no successful harvest in the last 8 days (`max_source_age_days`), or its latest run failed, was partial or was rejected;
- a harvest lost more than 20% of its links compared with the source's last good harvest (`max_row_drop`; the harvest is *rejected*), or the published links of a required source fell by more than 20% compared with the last manifest;
- more than 2% of a source's requests failed (`max_error_rate`; the harvest is *partial* and resumes next run);
- the works or merge stage did not succeed;
- reconciliation with DataCite is incomplete for more than 5% of DataCite-cited datasets (`reconcile_threshold`; see [Reconciliation](reconciliation.md)).

Overton and Crossref are optional: the same conditions produce warnings in the manifest, and their last good harvest is used. A partial works stage is a warning too.

### When a drop is real

If a source really has lost links (for example Scholexplorer stops serving similarity links), every harvest of it would be rejected and, after 8 days, publishing blocked. Once you have checked the drop, run with `--accept-drop SOURCE`:

```
python -m citations all --accept-drop scholexplorer
```

or set the workflow's `accept_drop` input. That harvest becomes the source's good harvest, and publishing is not blocked by the drop. Both are recorded: in the harvest run's details and as a warning in `manifest.json`. Unlike `--force`, it only waives the drop check, and only for the sources named.

### Forcing it

`--force` (the workflow's `force` input) publishes despite every problem. The problems are recorded in the manifest under `guards`, with `forced: true`. Use it only when you have checked the results by hand.

## Writing the results

1. Reconcile, then run the guards.
2. Read datasets, links and works from the store, and work out each dataset's counts and first citation.
3. Write `Results/v4`: `datasets.csv` and `.json`, `links.csv` and `.jsonl`, `works.csv` and `.json`, `reconciliation.csv`.
4. Write `Results/v3` unless `--no-v3`.
5. Write `manifest.json` last, with the SHA-256 and size of every other v4 file.

Every file is written to a temporary file in the same folder and renamed into place, so a reader never sees a half-written file and a failed write leaves the old one. The formats are in [Results/v4](../2-specification/results-v4.md) and [Results/v3](../2-specification/results-v3.md).

## Tests

`tests/test_pipeline.py`: `test_full_run` (every file, the manifest's hashes, v3), `test_failed_source_blocks_publishing_and_keeps_results`, `test_a_harvest_that_loses_most_rows_is_rejected`, `test_a_real_drop_can_be_accepted`, `test_overton_without_key_is_skipped_not_failed` and `test_v3_files_keep_the_v3_pipelines_types`. `tests/test_cli.py`: `test_publish_without_any_harvest_is_blocked`.
