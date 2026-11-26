---
title: Testing
status: current
updated: 2026-11-26
---

# Testing

> The tests run offline in a few seconds: a fake HTTP layer stands in for every API.

```
pip install -e ".[test]"
pytest
```

They run on every pull request and push to `main` (Python 3.10 and 3.12), and before every weekly run (Python 3.12). See [Workflows](ci-cd-workflows.md).

## What is where

| File | Covers |
| --- | --- |
| `tests/conftest.py` | `FakeClient`, which routes requests to Python functions, and the `settings` and `con` fixtures (a throwaway store) |
| `tests/test_pipeline.py` | End-to-end runs against `World`, a fake DataCite, Scholexplorer, Overton and Crossref: the full run and every output file; first-seen dates; a failed source; a rejected drop and an accepted one; resuming; retried lookups; an incomplete inventory; Overton without a key; v3 types |
| `tests/test_speed.py` | Rate limits and buckets, 429 counting, parallel harvests giving the same links as sequential ones, the sources really running at once, parallel citation strings, saving works as they arrive, progress logging |
| `tests/test_ids_relations_filters.py` | Identifier normalisation, relation direction and class, every exclusion rule |
| `tests/test_citation_text.py` | Citation strings: DOIs, formatter errors, fallbacks, plain text (ported from the v3 tests) |
| `tests/test_worktypes.py` | The Crossref work-type vocabulary and links for citing works |
| `tests/test_cli.py` | The command line: options, exit codes, errors |

Every test has a docstring saying what it checks.

## Writing a test

- Never call a real API. Add a route to `World.client()` in `tests/test_pipeline.py`, or build a `FakeClient` with the routes you need. An unexpected request fails the test.
- Break one thing at a time with `World`'s switches (`scholix_fail`, `scholix_empty`, `crossref_fail`, `total`).
- For citation strings, patch `citation_text._session` with a fake session (see `FakeFormatter`); `test_pipeline.py` does this for every test.
- A bug fix comes with a test that fails without the fix.
