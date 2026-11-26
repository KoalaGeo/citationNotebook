---
title: Workflows
status: current
updated: 2026-11-26
---

# Workflows

> The two GitHub Actions workflows: the weekly run, and the tests.

## Weekly citations: `.github/workflows/citations.yml`

`.github/workflows/citations.yml` runs every Sunday: tests, then `python -m citations all`, then it commits `Results/v4` and `Results/v3`. The SQLite store is carried between runs in the Actions cache. If the cache has been evicted, the run rebuilds it from scratch, which takes longer, and first-seen dates come from the published `links.csv`. The store and the DataCite snapshot are also kept as a 30-day run artifact. A failed or blocked run opens or updates an issue labelled `citations-pipeline`, and the previous results stay as they were.

Set the repository secret `OVERTON_API_KEY` and the variable `CITATIONS_MAILTO`.

A manual run ("Run workflow") takes three optional inputs: `force` (publish even if a guard fails), `skip` (sources not to harvest) and `accept_drop` (sources whose drop in links is real; see [Guards](../3-features/publishing-and-guards.md#guards)).

What the job does, in order:

1. Installs the package and runs the tests. A failing test stops the run.
2. Restores the store from the Actions cache.
3. Runs `python -m citations all --save-snapshot data/datacite_snapshot.json.gz`, with the manual run's inputs, and writes `python -m citations status` to the run summary.
4. Saves the store to the cache, whatever happened.
5. Uploads the store, the DataCite snapshot and the results as run artifacts (30 days).
6. Commits `Results/v4` and `Results/v3` if they changed, as "Weekly citations: N counted links".
7. On failure, opens or comments on an issue labelled `citations-pipeline` with the status.

The job's time limit is 340 minutes. A run stopped by it keeps what it fetched (see [Performance](performance-and-rate-limits.md)), and the next run carries on.

### Repository settings

| Name | Kind | Purpose |
| --- | --- | --- |
| `OVERTON_API_KEY` | secret | Overton; skipped without it |
| `CITATIONS_MAILTO` | variable | contact email for the polite rate limits |
| `CITATIONS_BRANCH` | variable, optional | the branch the pipeline runs on (default: the default branch) |
| `CITATIONS_COMMIT_RESULTS` | variable, optional | `false` to keep results out of git (artifact only) |

### Testing on a fork before a pull request

GitHub only starts scheduled and manual runs from a repository's default branch. To test a branch such as `v4` on a fork:

1. In the fork, enable Actions, and under Settings → Actions → General → Workflow permissions choose "Read and write".
2. Add the secret `OVERTON_API_KEY`, and the variables `CITATIONS_MAILTO`, `CITATIONS_BRANCH` = `v4` and, to keep result commits out of the branch you will open the pull request from, `CITATIONS_COMMIT_RESULTS` = `false`. The results are still uploaded as a run artifact.
3. Push a change under `citations/`, to `pyproject.toml` or to the workflow on `v4` to start a run. Use "Re-run all jobs" on that run to repeat it.

Upstream needs none of these variables: the workflow runs on the default branch, and pushes do not start it.

## Tests: `.github/workflows/tests.yml`

Runs `pytest` on Python 3.10 (the oldest `pyproject.toml` allows) and 3.12 (what the weekly run uses), for every pull request and every push to `main`. See [Testing](testing.md).
