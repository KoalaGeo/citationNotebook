"""Write Results/v3/latest_results.{csv,json} + filtered_out_df.csv in the
schema the API already ingests -- the refactor changes how the data is built,
not what the API sees.

Kept identical to the notebook output:
  * CSV: utf-8-sig, same column order (including the legacy data_page_number /
    data_self_link columns, always empty), lists rendered pandas-style.
  * JSON: grouped by data_publisher at the top level, records inside (without
    data_publisher), ensure_ascii=False.
  * date_added: carried over from the previous latest_results.csv for known
    (data_doi, publication_doi) pairs; today's date for new ones.

One deliberate improvement: missing values are written as JSON null. The old
pandas path emitted literal NaN tokens, which is not valid JSON and breaks
strict parsers; anything that accepted NaN also accepts null.
"""

import os
from datetime import date

import pandas as pd

RENAME = {
    "relation_type": "relation_type_id",
    "pub_doi": "publication_doi",
    "pub_title": "publication_title",
    "pub_date": "publication_date",
    "pub_authors": "publication_authors",
    "source_id": "citation_event_source",
    "pub_type": "publication_type",
    "pub_citation_str": "PubCitationStr",
}

# Exact column order of the committed Results/v3/latest_results.csv.
CSV_COLUMNS = ["data_doi", "data_publisher", "data_title",
               "data_publication_year", "data_authors", "relation_type_id",
               "publication_doi", "publication_title", "publication_date",
               "publication_authors", "citation_event_source", "pub_publisher",
               "publication_type", "data_page_number", "data_self_link",
               "publicationYear", "PubCitationStr", "data_doi_url",
               "publication_doi_url", "date_added"]


def finalize(df, previous_csv=None, today=None):
    """Filtered frame (+ pub_citation_str) -> the final API-schema frame."""
    df = df.copy()

    df["data_doi_url"] = "doi.org/" + df["data_doi"].astype(str)
    df["publication_doi_url"] = df["pub_doi"].apply(
        lambda x: f"doi.org/{x}" if isinstance(x, str) and x.startswith("10.") else x)

    df = df.rename(columns=RENAME)

    # Legacy columns the committed output still carries (always empty now).
    df["data_page_number"] = None
    df["data_self_link"] = None

    # date_added: keep the date first seen, from last week's published CSV.
    today_str = str(today or date.today())
    date_map = {}
    if previous_csv and os.path.isfile(previous_csv):
        old = pd.read_csv(previous_csv, encoding="utf-8-sig")
        if {"data_doi", "publication_doi", "date_added"} <= set(old.columns):
            dedup = old.drop_duplicates(subset=["data_doi", "publication_doi"])
            date_map = {(r.data_doi, r.publication_doi): r.date_added
                        for r in dedup.itertuples(index=False)}
    df["date_added"] = [
        date_map.get((row.data_doi, row.publication_doi), today_str)
        for row in df.itertuples(index=False)]

    return df[CSV_COLUMNS]


def write_outputs(df, filtered_out, results_dir="Results/v3"):
    os.makedirs(results_dir, exist_ok=True)

    csv_path = os.path.join(results_dir, "latest_results.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    filtered_path = os.path.join(results_dir, "filtered_out_df.csv")
    filtered_out.to_csv(filtered_path, index=False)

    json_path = os.path.join(results_dir, "latest_results.json")
    grouped = {}
    for publisher, chunk in df.groupby("data_publisher", dropna=False):
        records = chunk.drop(columns=["data_publisher"])
        # NaN -> None so the JSON contains valid nulls, never NaN tokens.
        records = records.astype(object).where(records.notna(), None)
        grouped[publisher] = records.to_dict(orient="records")
    import json as _json
    with open(json_path, "w", encoding="utf-8") as fh:
        fh.write(_json.dumps(grouped, ensure_ascii=False, allow_nan=False))

    return csv_path, json_path, filtered_path
