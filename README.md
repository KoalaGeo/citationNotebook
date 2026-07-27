# NERC dataset citation pipeline

Plain-Python refactor of the `citationNotebook` weekly pipeline. Same inputs
(DataCite, OpenAIRE Scholexplorer, Overton, doi.org), same outputs
(`Results/v3/latest_results.{csv,json}` + `filtered_out_df.csv` in the exact
schema the API ingests) — no notebooks, no pickles, one scheduled job.

## Run it

```bash
pip install -e .
python -m citations all --workers 8      # the whole weekly run
```

Or step by step (same order `all` uses):

```bash
python -m citations dois       # NERC dataset list from DataCite -> sqlite
python -m citations fetch      # citations: datacite events + scholix v3 + overton
python -m citations enrich     # doi.org metadata for new publication DOIs
python -m citations export     # filters + citation strings + Results/v3/*
```

Useful flags: `--source scholix` (fetch one source), `--limit 20` (smoke test),
`--no-fetch` (export from caches only), `--db path.db`, `--workers N`.

Set `OVERTON_API_KEY` in the environment (GitHub Actions: a repository secret).
The legacy in-repo key still works as a fallback but should be rotated.

## Layout

```
citations/
  cli.py          orchestrates: dois -> fetch -> enrich -> export
  http.py         one Session (retries/backoff/UA) + bounded parallel_map
  normalize.py    pure transforms: publisher mapping, DOI strip, year split,
                  publication-type merge  (fully unit-tested)
  sources/
    datacite.py   /dois dataset list + /events citation events
    scholix.py    Scholexplorer v3 (targetPid; active-voice semantics)
    overton.py    policy documents (sequential, >=1s between calls)
    doiorg.py     CSL metadata + registry type fallback + citation strings
  store.py        sqlite: datasets, citations, per-DOI caches, fetch_log
  merge.py        dedupe (source priority) + the reviewed filter logic
  export.py       API-schema rename, date_added carry-over, CSV/JSON writers
tests/            17 tests over parsers, filters, dedupe, export schema
```

## Design notes (what changed and why)

* **SQLite replaces the .pkl intermediates.** Pickles pinned pandas (they break
  across versions); `citations.db` is typed, greppable, and *incremental*: the
  `pub_info` and `citation_strings` tables cache per-DOI lookups, so a weekly
  run only fetches metadata/strings for **new** publications. Those two steps
  were the old pipeline's multi-hour tail. The db is a cache, not a source of
  truth — delete it and everything rebuilds. In CI it lives in `actions/cache`.
* **One job replaces five staggered crons.** The old workflows ran at 00:00,
  02:00, 04:00, 12:00, 23:00 and hoped their predecessors had finished and
  pushed. One process makes ordering deterministic and leaves one commit.
* **Scholix migrated to v3.** v3 stores relations active-voice, so citations of
  a dataset are found via `targetPid=<doi>` and the citing work is the link's
  `source`; the semantic lives in `RelationshipType.SubType`. The v2 code
  queried `sourcePid` and filtered `Name == "IsReferencedBy"` (a Name v3 never
  returns) — the wrong direction *and* a dead filter, i.e. the Scholix half of
  issue #11. Per-record error handling means one malformed link no longer drops
  a whole page.
* **The reviewed bug fixes are ported, with tests pinning them:**
  #17 (UTF-8 citation strings — no more latin1 crash on en-dash page ranges),
  the year filter that silently dropped unknown-year rows (#11 contributor),
  the peer-review step un-doing the title filter, `publisher` taken from the
  CSL `publisher` field, the escaped GBIF regex, and dedupe order preserved
  (datacite > scholex > overton, matching the old concat-keep-first).
* **One doi.org lookup per publication DOI** now serves both the DataCite
  metadata fill and the Scholix type check (previously two separate passes).
* **Speed comes from parallelism, not pandas tricks** — the runtime is
  thousands of small HTTP calls. Scholix / enrich / citation strings run on a
  small thread pool (`--workers`); Overton stays sequential at >=1s per call to
  respect the keyed API.

## Output parity

`export.py` reproduces the committed production files: identical CSV column
order (including the legacy, now-empty `data_page_number` / `data_self_link`
columns), utf-8-sig BOM, publisher-grouped JSON with `data_publisher` removed
from records, and `date_added` carried over from the previous published CSV.
One deliberate improvement: missing values are valid JSON `null`, whereas the
old pandas path wrote literal `NaN` tokens (invalid JSON that strict parsers
reject). `Results/intermediate_data/nerc_datacite_dois.json` is still written
for continuity; the other intermediates (`latest_results_*.csv/.pkl`) no
longer exist — the same information is queryable in `citations.db`.

## Tests

```bash
pip install -e .[dev]
pytest
```

Parsers are tested against fixture payloads taken from the real APIs (the
Scholix fixture is the documented v3 response), so "the API changed shape"
becomes a failing test with a diff, not a silent empty result.

## Migration checklist

1. Add this package to the repo; delete the five `regular_*.yml` workflows and
   `regular_Data_Citations.yml` in favour of `weekly_citations.yml`.
2. Add `OVERTON_API_KEY` as a repository secret; rotate the old key.
3. First run: `python -m citations all` locally or via workflow_dispatch, then
   diff `Results/v3/latest_results.csv` against the previous commit. Expect
   *more* rows (the Scholix v3 direction fix + the year-filter fix both recover
   citations); spot-check the DOIs from issues #11/#17.
4. Once green, the notebooks, `citations_fun/`, `executed_notebooks/` and the
   pkl intermediates can be removed (see CLEANUP.md from the earlier review).
