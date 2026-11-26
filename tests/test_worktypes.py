"""Tests for the work-type vocabulary (``citations.worktypes``) and links for citing works."""

import pytest

from citations import db
from citations.ids import work_url
from citations.worktypes import CROSSREF_TYPES, crossref_type, datacite_type


@pytest.mark.parametrize("value, source, expected", [
    ("journal-article", None, "journal-article"),            # Crossref, unchanged
    ("posted-content", "crossref", "posted-content"),
    ("article-journal", "datacite", "journal-article"),      # CSL
    ("article", "datacite", "posted-content"),
    ("thesis", "datacite", "dissertation"),
    ("chapter", None, "book-chapter"),
    ("graphic", "datacite", "other"),
    ("JournalArticle", None, "journal-article"),             # DataCite resourceTypeGeneral
    ("Preprint", None, "posted-content"),
    ("ConferencePaper", None, "proceedings-article"),
    ("conferencepaper", "datacite", "proceedings-article"),  # as v4 used to store it
    ("PeerReview", None, "peer-review"),
    ("Software", None, "other"),
    ("publication", "scholexplorer", "other"),               # Scholix: literature, nothing more
    ("Publication", "overton", "report"),                    # Overton document series
    ("Working paper", "overton", "report"),
    ("Scholarly article", "overton", "journal-article"),
    ("policy-document", "overton", "report"),
    (None, None, None),
    ("", "crossref", None),
])
def test_crossref_type(value, source, expected):
    """Crossref, CSL, DataCite, Scholexplorer and Overton type names each map to a Crossref type."""
    assert crossref_type(value, source) == expected


def test_every_result_is_a_crossref_type_and_mapping_is_idempotent():
    """Every mapped type is a Crossref type, and mapping it again leaves it unchanged."""
    for value, source in [("article-journal", "datacite"), ("Working paper", "overton"), ("Image", None),
                          ("publication", "scholexplorer"), ("Scholarly article", "overton")]:
        once = crossref_type(value, source)
        assert once in CROSSREF_TYPES
        assert crossref_type(once, source) == once


def test_datacite_type_prefers_resource_type_general():
    """A DataCite record's resourceTypeGeneral is used unless it is too broad, when the CSL type is used."""
    assert datacite_type({"resourceTypeGeneral": "Preprint", "citeproc": "article"}) == "posted-content"
    assert datacite_type({"resourceTypeGeneral": "Text", "citeproc": "article-journal"}) == "journal-article"
    assert datacite_type({"resourceTypeGeneral": "Dataset", "citeproc": "dataset"}) == "dataset"
    assert datacite_type({"resourceTypeGeneral": "Text"}) == "other"
    assert datacite_type({}) is None


def test_types_cached_before_normalisation_are_mapped_once(tmp_path):
    """Work types stored before normalisation are mapped when the store is opened, and only once."""
    path = tmp_path / "s.sqlite"
    con = db.connect(path)
    con.executemany("INSERT INTO works (citing_id, work_type, metadata_source) VALUES (?, ?, ?)", [
        ("10.1/a", "article-journal", "datacite"), ("https://gov.example/p", "Working paper", "overton"),
        ("10.1/b", "journal-article", "crossref"), ("https://x.example", None, None)])
    con.execute("DELETE FROM meta WHERE key='work_type_vocabulary'")   # a store from before this change
    con.commit()
    con.close()
    for _ in range(2):
        con = db.connect(path)
        types = dict(con.execute("SELECT citing_id, work_type FROM works").fetchall())
        con.close()
        assert types == {"10.1/a": "journal-article", "https://gov.example/p": "report",
                         "10.1/b": "journal-article", "https://x.example": None}


@pytest.mark.parametrize("citing_id, kind, expected", [
    ("10.1234/abc", "doi", "https://doi.org/10.1234/abc"),
    ("https://gov.example/policy.pdf", "url", "https://gov.example/policy.pdf"),
    ("pmid:12345", "pmid", "https://pubmed.ncbi.nlm.nih.gov/12345/"),
    ("pmc:PMC678", "pmc", "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC678/"),
    ("hdl:10013/epic.1", "handle", "https://hdl.handle.net/10013/epic.1"),
])
def test_work_url(citing_id, kind, expected):
    """Each identifier type gives a resolvable link."""
    assert work_url(citing_id, kind) == expected
