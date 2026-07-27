"""Merge + filter: the logic where the historical bugs lived, kept as pure
functions over a DataFrame so every rule is unit-testable.

filter_citations is the reviewed/fixed port of filterCitations.py:
  * one frame carried through every step (the old version recomputed from the
    original input at the peer-review step, undoing the title filter),
  * years coerced with pd.to_numeric(errors="coerce") and unknown-year rows
    KEPT (the old .astype(float) NaN comparison silently dropped them from both
    the kept AND the filtered-out frames -- a source of "missing citations", #11),
  * na-safe .str accessors, escaped GBIF regex.
"""

import pandas as pd

from .normalize import merge_publication_types, pub_year_splitter, strip_doi_url
from .sources.doiorg import NOT_GIVEN

# Dedupe order over (data_doi, pub_doi): first source wins -- the same
# precedence as the old pd.concat([dataCite, scholex, overton]) + keep="first".
SOURCE_PRIORITY = {"datacite": 0, "scholex": 1, "overton": 2}

TITLE_FILTERS = ("Comment on", "Reply on", "Reply to comment by", "final response")
EXCLUDED_DOI_PATTERN = "|".join(("egusphere", r"10\.15468"))  # abstracts; GBIF downloads


def build_frame(citation_rows, datasets, pub_info_lookup):
    """citations + datasets + per-DOI publication metadata -> one DataFrame.

    pub_info_lookup: dict pub_doi -> {title, date, authors, publisher, type}
    (the doi.org cache). DataCite event rows take all their publication fields
    from it; Scholix rows only refine pub_type via merge_publication_types;
    Overton rows are already complete.
    """
    rows = sorted(citation_rows,
                  key=lambda r: SOURCE_PRIORITY.get(r["source_group"], 9))
    assembled, seen = [], set()
    for row in rows:
        pub_doi = strip_doi_url(row["pub_doi"])
        key = (row["data_doi"], pub_doi)
        if key in seen:
            continue
        seen.add(key)

        dataset = datasets.get(row["data_doi"], {})
        info = pub_info_lookup.get(pub_doi)

        if row["source_group"] == "datacite":
            info = info or {}
            pub_title = info.get("title")
            pub_date = info.get("date")
            pub_authors = info.get("authors")
            pub_publisher = info.get("publisher")
            pub_type = info.get("type")
        else:
            pub_title = row.get("pub_title")
            pub_date = row.get("pub_date")
            pub_authors = row.get("pub_authors")
            pub_publisher = row.get("pub_publisher")
            pub_type = row.get("pub_type")
            if row["source_group"] == "scholex":
                doiorg_type = (info or {}).get("type", "unknown") \
                    if isinstance(pub_doi, str) and "10." in pub_doi else "not a doi"
                pub_type = merge_publication_types(pub_type, doiorg_type or "unknown")

        assembled.append({
            "data_doi": row["data_doi"],
            "data_publisher": dataset.get("data_publisher"),
            "data_title": dataset.get("data_title"),
            "data_publication_year": dataset.get("data_publication_year"),
            "data_authors": dataset.get("data_authors"),
            "relation_type": row.get("relation_type"),
            "pub_doi": pub_doi,
            "pub_title": pub_title,
            "pub_date": pub_date if pub_date is not None else NOT_GIVEN,
            "pub_authors": pub_authors,
            "source_id": row.get("source_id"),
            "pub_publisher": pub_publisher,
            "pub_type": pub_type,
        })

    df = pd.DataFrame(assembled)
    if not df.empty:
        df["publicationYear"] = df["pub_date"].apply(pub_year_splitter)
    return df


def filter_citations(df):
    """Remove citations we don't surface; returns (kept_df, filtered_out_df)."""
    df = df.copy()
    filtered_out_parts = []

    # 1. Comments / replies on pre-prints (by title prefix).
    is_comment = df["pub_title"].astype("string").str.startswith(TITLE_FILTERS, na=False)
    filtered_out_parts.append(df[is_comment])
    df = df[~is_comment]

    # 2. Peer-review publication type.
    is_peer_review = df["pub_type"].astype("string").str.startswith("peer-review", na=False)
    filtered_out_parts.append(df[is_peer_review])
    df = df[~is_peer_review]

    # 3. Unwanted publication DOIs (conference abstracts; GBIF dataset downloads).
    is_excluded = df["pub_doi"].astype("string").str.contains(
        EXCLUDED_DOI_PATTERN, na=False, regex=True)
    filtered_out_parts.append(df[is_excluded])
    df = df[~is_excluded]

    # 4. The publication must not pre-date the data it cites. NaN comparisons
    #    are False, so rows with an unknown year are KEPT (not silently lost).
    pub_year = pd.to_numeric(df["publicationYear"], errors="coerce")
    data_year = pd.to_numeric(df["data_publication_year"], errors="coerce")
    predates = pub_year < data_year
    filtered_out_parts.append(df[predates])
    df = df[~predates]

    filtered_out = (pd.concat(filtered_out_parts, ignore_index=True)
                    if filtered_out_parts else df.iloc[0:0].copy())
    return df.reset_index(drop=True), filtered_out
