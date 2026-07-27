"""Merge, filter, and export-schema tests -- the logic where the historical
bugs (issues #11/#17 contributors) lived."""
import json

import pandas as pd

from citations.export import CSV_COLUMNS, finalize, write_outputs
from citations.merge import build_frame, filter_citations

DATASETS = {
    "10.5285/data1": {"data_doi": "10.5285/data1",
                      "data_publisher": "National Geoscience Data Centre (NGDC)",
                      "data_title": "Dataset one", "data_publication_year": 2019,
                      "data_authors": ["Farr, G"]},
}


def cite(pub_doi, group, **kw):
    row = {"data_doi": "10.5285/data1", "pub_doi": pub_doi,
           "source_group": group, "source_id": kw.pop("source_id", group),
           "relation_type": "cites", "pub_title": kw.pop("pub_title", "T"),
           "pub_date": kw.pop("pub_date", "2020-01-01"),
           "pub_authors": ["A"], "pub_type": kw.pop("pub_type", "literature"),
           "pub_publisher": "J"}
    row.update(kw)
    return row


def test_dedupe_priority_matches_old_concat_order():
    rows = [cite("10.1/x", "overton", pub_title="from overton"),
            cite("10.1/x", "datacite", source_id="datacite-crossref"),
            cite("10.1/x", "scholex", pub_title="from scholex")]
    info = {"10.1/x": {"title": "From doi.org", "date": "1/1/2020",
                       "authors": [["A", "B"]], "publisher": "P",
                       "type": "journal-article"}}
    df = build_frame(rows, DATASETS, info)
    assert len(df) == 1
    # datacite wins (old order: [dataCite, scholex, overton], keep first)
    assert df.iloc[0]["source_id"] == "datacite-crossref"
    assert df.iloc[0]["pub_title"] == "From doi.org"   # datacite fields from doi.org


def test_scholex_type_merged_with_doiorg():
    rows = [cite("10.1/y", "scholex", pub_type="literature")]
    info = {"10.1/y": {"type": "journal-article"}}
    df = build_frame(rows, DATASETS, info)
    assert df.iloc[0]["pub_type"] == "journal-article"  # literature -> more specific


def test_filters():
    base = dict(data_doi="10.5285/data1", data_publisher="NGDC",
                data_title="D", data_publication_year=2019, data_authors=[],
                relation_type="cites", pub_authors=[], source_id="scholex",
                pub_publisher="J")
    df = pd.DataFrame([
        dict(base, pub_doi="10.1/keep", pub_title="Real paper",
             pub_type="journal-article", pub_date="2020-01-01",
             publicationYear="2020"),
        dict(base, pub_doi="10.1/comment", pub_title="Comment on something",
             pub_type="journal-article", pub_date="2020-01-01",
             publicationYear="2020"),
        dict(base, pub_doi="10.1/pr", pub_title="Review",
             pub_type="peer-review", pub_date="2020-01-01",
             publicationYear="2020"),
        dict(base, pub_doi="10.15468/dl.abc", pub_title="GBIF download",
             pub_type="dataset", pub_date="2020-01-01", publicationYear="2020"),
        dict(base, pub_doi="10.1/early", pub_title="Too early",
             pub_type="journal-article", pub_date="2015-01-01",
             publicationYear="2015"),
        dict(base, pub_doi="10.1/noyear", pub_title="Unknown year kept",
             pub_type="journal-article", pub_date="Info not given",
             publicationYear=None),
    ])
    kept, filtered_out = filter_citations(df)
    assert set(kept["pub_doi"]) == {"10.1/keep", "10.1/noyear"}  # None-year KEPT
    assert len(kept) + len(filtered_out) == len(df)              # nothing vanishes
    assert set(filtered_out["pub_doi"]) == \
        {"10.1/comment", "10.1/pr", "10.15468/dl.abc", "10.1/early"}


def test_finalize_schema_and_date_added(tmp_path):
    kept = pd.DataFrame([{
        "data_doi": "10.5285/data1", "data_publisher": "NGDC",
        "data_title": "D", "data_publication_year": 2019,
        "data_authors": ["Farr, G"], "relation_type": "cites",
        "pub_doi": "10.1/keep", "pub_title": "Real paper",
        "pub_date": "2020-01-01", "pub_authors": ["A"],
        "source_id": "scholex", "pub_publisher": "J",
        "pub_type": "journal-article", "publicationYear": "2020",
        "pub_citation_str": "A. (2020). Real paper.",
    }, {
        "data_doi": "10.5285/data1", "data_publisher": "NGDC",
        "data_title": "D", "data_publication_year": 2019,
        "data_authors": ["Farr, G"], "relation_type": "references",
        "pub_doi": "http://gov.example/x", "pub_title": "Policy",
        "pub_date": "2021-01-01", "pub_authors": ["Gov"],
        "source_id": "overton", "pub_publisher": "Gov",
        "pub_type": "Publication", "publicationYear": "2021",
        "pub_citation_str": "not a doi",
    }])

    prev = tmp_path / "latest_results.csv"
    pd.DataFrame([{"data_doi": "10.5285/data1", "publication_doi": "10.1/keep",
                   "date_added": "2024-01-07"}]).to_csv(prev, index=False,
                                                        encoding="utf-8-sig")

    final = finalize(kept, previous_csv=str(prev), today="2026-07-26")
    assert list(final.columns) == CSV_COLUMNS
    by_doi = final.set_index("publication_doi")
    assert by_doi.loc["10.1/keep", "date_added"] == "2024-01-07"        # carried over
    assert by_doi.loc["http://gov.example/x", "date_added"] == "2026-07-26"  # new
    assert by_doi.loc["10.1/keep", "data_doi_url"] == "doi.org/10.5285/data1"
    assert by_doi.loc["10.1/keep", "publication_doi_url"] == "doi.org/10.1/keep"
    assert by_doi.loc["http://gov.example/x", "publication_doi_url"] == \
        "http://gov.example/x"                                          # URL untouched

    out = tmp_path / "out"
    csv_path, json_path, _ = write_outputs(final, kept.iloc[0:0], str(out))
    raw = open(csv_path, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")                              # utf-8-sig BOM
    payload = json.loads(open(json_path, encoding="utf-8").read())      # strict JSON
    assert list(payload) == ["NGDC"]                                    # publisher-keyed
    record = payload["NGDC"][0]
    assert "data_publisher" not in record
    assert record["data_authors"] == ["Farr, G"]                        # real list
    assert record["data_page_number"] is None                           # null, not NaN
