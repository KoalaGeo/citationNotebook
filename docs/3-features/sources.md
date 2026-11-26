---
title: Sources
status: current
updated: 2026-11-26
---

# Sources

> The four APIs links are harvested from, and how a harvest is run, resumed and checked.

| Source | Required | What it finds | Requests |
| --- | --- | --- | --- |
| [DataCite](#datacite) | yes | the citations behind DataCite's `citationCount`, and incoming relations in dataset metadata | two or more per *cited* dataset |
| [Scholexplorer](#scholexplorer) | yes | every Scholix link to each dataset | one or more per dataset |
| [Overton](#overton) | no | policy documents citing the datasets | one upload, then one per page of results |
| [Crossref](#crossref) | no | data citations Crossref members deposit | one or more per dataset |

A **required** source must have a recent, successful harvest or publishing is refused. An **optional** source's problems are warnings, and its last good harvest is used.

## How a harvest runs

`citations/harvest.py` runs every source the same way:

1. **Start or resume.** If the source's latest harvest is unfinished (`running`, because the job was stopped, or `partial`) and started within `resume_window_days` (8), that run is resumed. Otherwise a new run starts.
2. **Fetch.** The source fetches its keys (usually dataset DOIs) in worker threads. Each key's links are stored and the key logged in `fetch_log` as it arrives, and committed straight away. A resumed run skips keys already logged `ok`, so it only retries what failed. Progress is logged every minute.
3. **Decide the status:**

| Status | When | Effect |
| --- | --- | --- |
| `success` | none of the below | becomes the source's good run; older runs' raw links are deleted |
| `partial` | more than `max_error_rate` (2%) of requests failed | previous good run kept; the next run resumes this one |
| `rejected` | more than `max_row_drop` (20%) fewer links than the good run | previous good run kept, unless the source was named in `--accept-drop` |
| `failed` | the source raised an error | previous good run kept |
| `skipped` | the source cannot run here (Overton with no key) | previous good run kept |

The four sources run at the same time, one thread and store connection each (`run_harvests`). Each records `throttled_429`, the rate-limited responses it got, and any counts of what it dropped and why in the run's `details`.

## DataCite

`citations/sources/datacite.py`. Two parts:

1. **Dataset metadata.** Every incoming relation the data centre wrote into the dataset's own `relatedIdentifiers` (already downloaded by the inventory, so no requests). Provenance `metadata`.
2. **Counted citations.** For each dataset with a `citationCount` above zero: its record's `relationships.citations`, which is the exact list behind the count, then `/events?doi=` to label each link with the event's source and relation. DataCite events can put the dataset on either side, so each is turned round to the dataset's side. A citation DataCite counts but no event states as incoming is kept as `IsCitedBy`: DataCite's verdict stands, and what the event said is kept in `source_relations`.

Provenance becomes the label in `sources`: `datacite:crossref` for journal reference lists Crossref deposits, `datacite:metadata` for relations from DataCite metadata.

*v3:* asked the events API only for `is-cited-by`, `is-referenced-by` and `is-supplement-to` with the dataset as subject, so it never saw journal reference lists (Crossref `references` events with the article as subject): 99% of the DataCite links missing from v3.

## Scholexplorer

`citations/sources/scholexplorer.py`. For each dataset, `https://api.scholexplorer.openaire.eu/v3/Links?targetPid=<doi>`, 100 links a page. Links are stated "source *relation* target" with the dataset as target, so each relation is turned round. The citing work's identifier is its DOI if it has one, else its PMID, PMC, handle or URL. Outgoing relations and links with no usable identifier are counted and dropped. What Scholexplorer says about the work (title, date, type, publisher, authors) is kept as a hint for the works stage.

*v3:* counted every relation as a citation; similarity recommendations (`HasAmongTopNSimilarDocuments`) were 44% of its rows.

## Overton

`citations/sources/overton.py`. Needs the `OVERTON_API_KEY` environment variable; without it the source is `skipped`. Uploads the inventory's DOIs as an Overton DOI set, then pages through the documents that cite them. **Every** highlight of a document is used, so a policy document citing three datasets gives three links. The citing identifier is the document's URL, and the relation is `IsReferencedBy`.

*v3:* used only each document's first highlight, and its API key was in the code. It is still in the git history and should be rotated.

## Crossref

`citations/sources/crossref.py`. For each dataset, Crossref's beta data-citations endpoint, `https://api.crossref.org/beta/datacitations/?object-id=<doi>`, following its cursor. Crossref states each relation with the article as subject; its own names (`references`, `is_part_of`, `based-on-data` ...) are mapped to DataCite's. The endpoint is a beta, so an unknown relation is counted rather than guessed. A source v3 did not use.

## Adding a source

1. Add `citations/sources/<name>.py` with `SOURCE`, `BUCKETS` and `harvest(ctx, run_id)`. Use `per_key` for one request per dataset, or `write_links` and `log_fetch` directly for anything else (see Overton).
2. Return `RawLink`s with the relation turned to the dataset's side (`citations.relations.dataset_side`) and the identifier normalised (`citations.ids.normalise_id`).
3. Register it in `citations/sources/__init__.py` and add it to `REQUIRED_SOURCES` or `OPTIONAL_SOURCES` in `citations/config.py`.
4. Add its API's rate limit to `api_limits` in `citations/http.py`.
5. Give it an API in the fake world in `tests/test_pipeline.py`, and name it for v3's `citation_event_source` in `LEGACY_SOURCE` in `publish.py` (otherwise v3 rows use its own name).

## Tests

`tests/test_pipeline.py`: `test_full_run`, `test_failed_source_blocks_publishing_and_keeps_results`, `test_a_harvest_that_loses_most_rows_is_rejected`, `test_a_real_drop_can_be_accepted`, `test_a_partial_harvest_is_resumed_by_next_weeks_run`, `test_overton_without_key_is_skipped_not_failed`. `tests/test_speed.py`: parallel harvests and progress logging.
