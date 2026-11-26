# NERC EDS dataset citations: project guide

> For anyone changing this repository, person or coding agent. Read it before you start.

## Project overview

A Python pipeline that harvests the links between NERC Environmental Data Service datasets (DataCite client `bl.nerc`) and the works that cite or relate to them, from DataCite, Scholexplorer, Overton and Crossref. It classifies each link and publishes CSV and JSON results to `Results/v4`, plus a v3-compatible copy in `Results/v3` that the EDS citation API reads. It runs weekly on GitHub Actions.

- `python -m citations all` runs every stage: inventory, harvest, works, merge, publish.
- State between runs is a SQLite store, `data/citations.sqlite`, which is never committed.
- Two runtime dependencies: `requests` and `urllib3`.

## Repository structure

```
citationNotebook/
├── .github/workflows/
│   ├── citations.yml      the weekly run (Sundays 01:17 UTC); commits Results/
│   └── tests.yml          pytest on Python 3.10 and 3.12, for pull requests and main
├── citations/             the pipeline package
│   ├── cli.py             commands and the "all" run
│   ├── config.py          Settings (every threshold), sources, data centres
│   ├── db.py              SQLite schema and run bookkeeping
│   ├── http.py            one HTTP client: retries, per-API rate limits, parallel map
│   ├── inventory.py       stage 1
│   ├── harvest.py         running a source: resume, error rate, row drop, good run
│   ├── sources/           one module per API
│   ├── works.py           stage 3: metadata and citation strings
│   ├── citation_text.py   citation formatting and plain text (ported from v3)
│   ├── worktypes.py       Crossref work-type vocabulary
│   ├── ids.py             identifier normalisation
│   ├── relations.py       relation vocabulary, direction and class
│   ├── filters.py         exclusion rules
│   ├── merge.py           stage 4
│   ├── reconcile.py       comparison with DataCite's citationCount
│   ├── guards.py          checks before publishing
│   └── publish.py         stage 5: Results/v4, Results/v3, manifest
├── tests/                 offline tests; conftest.py has the fake HTTP client
├── Results/
│   ├── v4/                published results (written by the workflow)
│   ├── v3/                v3-compatible copy for the EDS citation API (written by the workflow)
│   └── v1/, v2/           old, no longer updated
├── inspect_results.ipynb  validation, overview and comparison of published results
├── docs/                  documentation (see below)
├── pyproject.toml
└── README.md              short landing page
```

## Commands

```bash
pip install -e ".[test]"       # install, with pytest
pytest                         # all tests, offline, a few seconds
python -m citations --help     # the commands
python -m citations status     # what ran, and what is in use
```

Never run `python -m citations all`, `harvest`, `works` or `publish` against the real APIs as a check: they take hours, call rate-limited APIs and overwrite `Results/`. The tests cover the pipeline end to end offline.

## Rules

1. **`Results/v3` must keep the v3 pipeline's shape and types exactly**: the same columns in the same order, the same encodings (BOM on `latest_results.csv` only), the JSON on one line, a float `data_publication_year`, placeholder text (`No title given`, `Info not given`) instead of empty values, and unpadded dates. The EDS citation API breaks otherwise. After any change to `publish.py`, run `test_v3_files_keep_the_v3_pipelines_types` and section 1c of `inspect_results.ipynb`. See `docs/2-specification/results-v3.md`.
2. **Don't edit `Results/` by hand.** The weekly workflow writes and commits it.
3. **Never commit `data/`**, the store or snapshots. They are in `.gitignore`.
4. **No secrets in code, tests, docs or commit messages.** Keys come from the environment (`OVERTON_API_KEY`) and are redacted from logs by `citations.http.redact`.
5. **Tests never call a real API.** Add a route to the fake world in `tests/test_pipeline.py` or a `FakeClient` (`tests/conftest.py`). A bug fix comes with a test that fails without it.
6. **Counting changes are visible changes.** A change to relation classes, exclusion rules or identifiers changes every consumer's numbers: update `docs/2-specification/counting-rules.md` in the same pull request and say so in the changelog.
7. **Keep the guards.** Don't weaken a guard or threshold to get a run to publish; `--accept-drop` and `--force` exist for a person to decide that.
8. **Keep pull requests small and focused**, with no unrelated changes.

## Code conventions

- Python 3.10 or later; modules with type hints start with `from __future__ import annotations`.
- Plain functions and dataclasses; no new runtime dependencies without a good reason.
- **Every module, class and function has a Google-style docstring**: a one-line summary, the why where it isn't obvious, then `Args:`, `Returns:` or `Yields:`, and `Raises:`. Markdown in docstrings (backticks for code), not reStructuredText or Sphinx roles. Every test has a one-line docstring saying what it checks. See `docs/5-technical/documentation.md`.
- Check docstrings with `ruff check --isolated --select D --config "lint.pydocstyle.convention='google'" citations tests`.
- Plain English and British spelling in docstrings, comments, docs and messages. Short sentences.
- Every HTTP request goes through `citations.http.HttpClient`, so it is rate limited. A new API needs its limit in `api_limits`.
- Every new setting goes in `Settings` in `citations/config.py`, documented in its docstring.
- Store writes are short transactions (`db.transaction`); the sources harvest in parallel threads.
- Errors in one item are recorded, not raised, so one bad DOI can't stop a harvest. A stage records its run's status with `db.finish_run`.

## Documentation structure

| Folder | Purpose |
| --- | --- |
| `docs/README.md` | Index: quick links, key concepts, getting started |
| `docs/1-vision/` | Principles, architecture, use cases |
| `docs/2-specification/` | Counting rules and the result formats. Consumers rely on these |
| `docs/3-features/` | One page per stage: how it works, settings, code, tests |
| `docs/4-roadmap/` | Changelog, current status, backlog |
| `docs/5-technical/` | Setup, workflows, rate limits, data store, testing, conventions |

Each page starts with front matter: `title`, `status` (`current`, `draft` or `planned`) and `updated` (date of the last real change).

## Documentation maintenance

| When you... | Update |
| --- | --- |
| Change what is counted or excluded | `docs/2-specification/counting-rules.md`, the changelog |
| Change a published file's columns or format | `docs/2-specification/results-v4.md` or `results-v3.md`, the changelog |
| Change how a stage works | its page in `docs/3-features/` |
| Add a source | `docs/3-features/sources.md`, `docs/5-technical/performance-and-rate-limits.md` |
| Add or change a setting or command | `docs/5-technical/setup.md`, and the `Settings` docstring |
| Change a workflow | `docs/5-technical/ci-cd-workflows.md` |
| Change the store's schema | `docs/5-technical/data-store.md` |
| Finish a piece of work | `docs/4-roadmap/CHANGELOG.md` (under Unreleased), and `current.md` or `backlog.md` if it moves an item |
| Plan new work | `docs/4-roadmap/backlog.md` |
| Fix a small bug | the commit message, and the changelog if users would notice |

Keep `README.md` short: it links to `docs/` rather than repeating it.

## Status indicators

| Symbol | Meaning |
| --- | --- |
| ✅ | Complete |
| 🔄 | In progress |
| ⚠️ | Needs update |
| 📋 | Planned |
| 💡 | Idea |
