---
title: Works and citation strings
status: current
updated: 2026-11-26
---

# Works and citation strings

> Metadata and a plain-text citation string for every citing work, fetched once and cached in the store. `citations/works.py`, `citations/citation_text.py` and `citations/worktypes.py`.

## Metadata

Every citing work found in a source's good harvest gets metadata from the first of these that applies:

1. **The inventory**, when the citing work is itself a NERC dataset (`metadata_source` `inventory`).
2. **Crossref or DataCite**, when it has a DOI. DOIs under prefixes known to be DataCite's (`DATACITE_PREFIXES`: NERC, Zenodo, figshare, Dryad, PANGAEA, GBIF ...) are looked up at DataCite first; any other DOI at Crossref first, then DataCite.
3. **The source's hint**, what the harvesting source said about the work, when it has no DOI or neither agency knows it. When several sources gave a hint, the order of preference is Scholexplorer, Overton, Crossref, DataCite.

The date is the work's `issued` date (Crossref: `issued`, else the print or online publication date, else `created`; DataCite: the `Issued` date, else the publication year), in ISO 8601 with its precision.

Metadata is fetched once and refreshed after `works_refresh_days` (90). Works are saved 500 at a time, so a run stopped by the job's time limit keeps what it fetched. A lookup that **fails** (rather than finding nothing) is stored with the source's hint and no `fetched_at`, so the next run tries it again; a work that already had metadata keeps it.

The stage is `partial` when more than 20% of DOI lookups failed, and `failed` if it raised an error.

## Work types

Each source names types its own way: Crossref `journal-article`; DataCite a `resourceTypeGeneral` (`JournalArticle`) and a CSL type (`article-journal`); Scholexplorer `publication`; Overton its document series (`Working paper`). `citations/worktypes.py` maps them all to [Crossref's vocabulary](https://api.crossref.org/types), which covers most citing works already and is what v3's `publication_type` always carried:

- names are compared lower case with anything but letters removed, so `JournalArticle` and `journal-article` match;
- a few other names are aliases (`Preprint` and CSL `article` are `posted-content`; `thesis` is `dissertation` ...);
- DataCite's `resourceTypeGeneral` is used unless it is too broad (`Text`, `Other`), when its CSL type is used;
- Overton's document series are `report`, except a scholarly article;
- anything else is `other`; nothing known is empty.

Stores written before this vocabulary are mapped once when opened (`_crossref_work_types` in `citations/db.py`).

## Citation strings

Each work gets a citation string once, from the first that applies:

| `citation_source` | From |
| --- | --- |
| `reused` | a real citation already published in `Results/v3`, or already in the store |
| `formatter` | DOI content negotiation: `doi.org` with `Accept: text/x-bibliography; style=apa; locale=en-GB`, which passes the request to the DOI's registration agency |
| `fallback` | built from the metadata: `Authors (Year). Title. Publisher. https://doi.org/DOI`. Only when there is a title |
| `link` | the work's link: its URL, or its `doi.org`, PubMed, PMC or Handle link |

A work whose string is only a fallback or a link gets a new one when better metadata arrives.

**Only real citations are used.** A formatter response is rejected if it is shorter than 20 characters or looks like an error: `Unknown style ...`, `DOI not found`, an HTML page, a JSON error (including `style-not-found` sent with HTTP 200) and similar (`FORMATTER_ERRORS`).

**A broken formatter fails the stage.** If fewer than `min_citation_success_rate` (half) of at least 20 lookups return a citation, formatting raises and the works stage fails, rather than writing degraded strings into the results. (From late February 2026 v3 wrote formatter error messages into its citation column.)

**Everything is plain text** (`plain_text`): HTML entities decoded (including double-escaped and title-cased ones such as `&Amp;`), inline markup removed (`<i>`, `<scp>`, MathML ...), `<sub>` and `<sup>` turned into Unicode where possible (N₂O, ¹³⁷Cs, m²), and line breaks collapsed. Text that only looks like a tag (`<S1-11> Effect of ...`) is kept.

Citation strings count against the registration agency's rate limit, so each request is paced in that agency's bucket (`doi.org/crossref` or `doi.org/datacite`).

## Tests

`tests/test_citation_text.py` (formatting, errors, fallbacks, plain text), `tests/test_worktypes.py` (the vocabulary), `test_a_failed_metadata_lookup_is_retried_next_run` in `tests/test_pipeline.py`, and `test_works_are_saved_as_they_arrive` and `test_parallel_citation_strings_match_sequential` in `tests/test_speed.py`.
