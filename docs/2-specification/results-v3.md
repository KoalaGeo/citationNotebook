---
title: Results/v3 (deprecated)
status: current
updated: 2026-11-26
---

# Results/v3 (deprecated)

> A copy of the results in the v3 pipeline's format, still written every run because the EDS citation API reads it. Written by `write_v3` in `citations/publish.py`.

## What must not change

The EDS citation API reads these files, so they keep the v3 pipeline's shape and types exactly:

| File | Columns | Encoding | Notes |
| --- | --- | --- | --- |
| `latest_results.csv` | the 18 of `V3_COLUMNS`, in order | UTF-8 **with** a BOM | counted links only |
| `filtered_out_df.csv` | the 14 of `V3_FILTERED_COLUMNS`, in order | UTF-8 without a BOM | excluded links |
| `latest_results.json` | the `latest_results` rows, grouped by `data_publisher` and without it | UTF-8, on **one line** with no trailing newline | |

And within them:

- `data_publication_year` is a float: `2012.0`.
- A missing value is v3's placeholder text, never an empty cell or `null`: `No title given` for `data_title`; `Info not given` for `publication_title`, `pub_publisher` and `publication_type` (and the `pub_` equivalents in `filtered_out_df.csv`).
- List columns (`data_authors`, `publication_authors`) are Python list literals in CSV, as pandas wrote them, and JSON arrays in JSON.
- Dates are not padded: `publication_date` is `YYYY`, `YYYY-MM` or `YYYY-MM-DD` as known.

Section 1c of `inspect_results.ipynb` checks all of this against upstream's files (`UPSTREAM_REPO` at `UPSTREAM_REF`): the same columns in the same order, the same encoding, and no kind of value a column or JSON field has never had upstream. **Run it after any change to `publish.py`.** `test_v3_files_keep_the_v3_pipelines_types` in `tests/test_pipeline.py` checks the same rules offline.

## How it is built

From v4's data, after the guards pass:

- each **counted** link is a `latest_results` row, with `date_added` taken from `first_seen`;
- each **excluded** link is a `filtered_out_df` row;
- links that are included but not counted (documentation, versions, similarity, dataset links) are not in v3 at all;
- `data_publisher` is the data centre's full name, else DataCite's publisher, else `Unknown data centre`;
- `citation_event_source` is one source per row, the first of `datacite`, `scholex`, `overton`, `crossref` that found the link;
- `relation_type_id` is the dataset-side relation in kebab case (`is-cited-by`).

## Differences in content from the v3 pipeline

Consumers may notice:

- **Fewer, more accurate rows.** Similarity, dataset-to-dataset and version links are no longer in it.
- EGUsphere preprints (`10.5194/egusphere-2023-...`) are in it. v3 excluded every EGUsphere DOI as a conference abstract; only EGU General Assembly abstracts are excluded now.
- `publication_date` is ISO 8601 at the precision known (was D/M/YYYY).
- `publication_authors` is a list of `"Family, Given"` strings for every source (DataCite rows were a list of `[given, family]` pairs). A work with no authors has `[]` (was `Info not given` or `not a doi`).
- `publication_type` is a Crossref type on every row. Scholexplorer's and Overton's `Publication` become `other` and `report`.
- `PubCitationStr` is never empty: a work with nothing to build a citation from has a link to it instead.
- Why each link in `filtered_out_df.csv` was excluded is in `Results/v4/links.csv` (`exclusion_reason`); the v3 file keeps its 14 columns.

`Results/v1` and `Results/v2` are no longer updated.

## Retiring it

Once the EDS citation API reads `Results/v4`, `Results/v3` can stop being written: run `publish --no-v3`, or set `write_v3` to `False` in `Settings`. See the [backlog](../4-roadmap/backlog.md).
