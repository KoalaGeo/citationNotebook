---
title: Performance and rate limits
status: current
updated: 2026-11-26
---

# Performance and rate limits

> How the run stays fast while keeping within every API's published limit. `citations/http.py` and `run_harvests` in `citations/harvest.py`.

The run spends almost all its time waiting on the APIs, within their published rate limits, so it overlaps that waiting rather than using more processes:

- The four sources are harvested at the same time, one thread and one store connection each. Each calls a different API, so the harvest takes as long as the slowest source (usually Crossref's data citations, which allow 3 list requests a second) instead of the sum.
- Within a source, and for citing-work metadata and citation strings, requests run in parallel (`--workers`, default 4), up to each API's limit.
- `citations/http.py` paces every request to the API's published limit (requests per second, and requests at once), just under it: Crossref's polite pool, 10/s for single records, 3/s for lists, 3 at once; DataCite, 1,000 requests per 5 minutes, which is also its cap for citation strings from DataCite DOIs; Overton, one a second. Without `CITATIONS_MAILTO` the lower anonymous limits are used. A slow API never holds up requests to the others.
- While harvesting, each source logs a progress line every minute: how many it has fetched, how fast, errors, rate-limited (429) responses so far and an estimate of the time left. Results are saved as each request finishes, so one slow request doesn't hold the rest back.
- Each harvest run and the works run record `throttled_429`, the number of rate-limited responses they got (see `python -m citations status` or the store), so a limit that has changed shows up.
- Harvested links, citing-work metadata and citation strings are saved as they arrive. A run stopped by the job's time limit keeps what it fetched, and the next run carries on from there.

## The limits

From `api_limits` in `citations/http.py`, set a little under each published limit:

| Bucket | With `CITATIONS_MAILTO` | Without | At once | Published limit |
| --- | --- | --- | --- | --- |
| `api.crossref.org/single` (one record) | 9/s | 4.5/s | 3 (1 without), shared with the other Crossref buckets | 10/s polite, 5/s public |
| `api.crossref.org/list` (queries, data citations) | 2.7/s | 0.9/s | as above | 3/s polite, 1/s public |
| `doi.org/crossref` (citation strings for Crossref DOIs) | 9/s | 4.5/s | as above | as single records |
| `api.datacite.org` | 3.2/s | 1.6/s | 4 | 1,000 per 5 minutes with contact details, 500 without |
| `doi.org/datacite` (citation strings for DataCite DOIs) | 3.2/s | 1.6/s | 4 | 1,000 per 5 minutes |
| `api.scholexplorer.openaire.eu` | 10/s | 10/s | 4 | none published (v3 used 10/s) |
| `app.overton.io` | 0.95/s | 0.95/s | 1 | one a second |

Sources: [Crossref's rate limits](https://crossref.org/blog/announcing-changes-to-rest-api-rate-limits/) (from December 2025) and [DataCite's](https://support.datacite.org/docs/rate-limit).

## How pacing works

Each request books the next turn in its bucket under a lock, then sleeps outside the lock, so a slow API (Overton, once a second) never holds up requests to the others. A semaphore per group caps the requests in flight. Retries (429 and 5xx, with backoff, honouring `Retry-After`) happen inside each request's slot.

## If an API changes its limit

`throttled_429` rising in `python -m citations status` is the sign. Change the numbers in `api_limits`, and the test `test_published_limits_depend_on_a_contact_email` with them.
