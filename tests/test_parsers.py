from citations.sources.datacite import parse_dataset_record, parse_event
from citations.sources.doiorg import parse_csl
from citations.sources.overton import parse_document
from citations.sources.scholix import parse_link

# --- Scholix v3: the documented live payload shape --------------------------

SCHOLIX_LINK = {
    "RelationshipType": {"Name": "IsRelatedTo", "SubType": "cites",
                         "SubTypeSchema": "datacite"},
    "source": {
        "Identifier": [
            {"ID": "10.1108/k-08-2023-1556", "IDScheme": "doi",
             "IDURL": "https://doi.org/10.1108/k-08-2023-1556"},
            {"ID": "50|doi_________::368a", "IDScheme": "openaireIdentifier"},
        ],
        "Title": "Study on urban green development efficiency",
        "Type": "literature",
        "Creator": [{"name": "Dan Liu", "identifier": []},
                    {"name": "Tiange Liu", "identifier": []}],
        "PublicationDate": "2024-05-15",
        "Publisher": [{"name": "Kybernetes", "identifier": []}],
    },
    "target": {"Identifier": [{"ID": "10.5285/abc", "IDScheme": "doi"}]},
}


def test_scholix_parse_link_reads_source_side():
    row = parse_link(SCHOLIX_LINK, "10.5285/abc")
    assert row["pub_doi"] == "10.1108/k-08-2023-1556"
    assert row["relation_type"] == "cites"          # semantic from SubType, not Name
    assert row["pub_title"].startswith("Study on urban")
    assert row["pub_authors"] == ["Dan Liu", "Tiange Liu"]
    assert row["pub_publisher"] == "Kybernetes"
    assert row["pub_type"] == "literature"
    assert row["data_doi"] == "10.5285/abc"


def test_scholix_missing_publisher_does_not_crash():
    link = {"RelationshipType": {"Name": "IsRelatedTo", "SubType": "references"},
            "source": {"Identifier": [{"ID": "10.1/x", "IDScheme": "doi"}],
                       "Publisher": []}}
    row = parse_link(link, "10.5285/abc")
    assert row["pub_publisher"] is None             # v2 crashed the whole page here
    assert row["relation_type"] == "references"


# --- DataCite ---------------------------------------------------------------

def test_datacite_dataset_record():
    record = {"attributes": {
        "doi": "10.5285/abc", "publisher": "NERC EDS British Oceanographic Data Centre",
        "titles": [{"title": "A dataset"}], "publicationYear": "2021",
        "creators": [{"name": "Smith, A"}, {"name": "Jones, B"}]}}
    row = parse_dataset_record(record)
    assert row["publisher"] == "British Oceanographic Data Centre (BODC)"
    assert row["publication_year"] == 2021
    assert row["authors"] == ["Smith, A", "Jones, B"]


def test_datacite_publisher_dict_variant():
    record = {"attributes": {"doi": "10.5285/x",
                             "publisher": {"name": "UK Polar Data Centre"},
                             "titles": [], "creators": []}}
    assert parse_dataset_record(record)["publisher"] == "Polar Data Centre (PDC)"


def test_datacite_event():
    event = {"attributes": {"subj-id": "https://doi.org/10.5285/abc",
                            "obj-id": "https://doi.org/10.1016/j.x",
                            "source-id": "datacite-crossref",
                            "relation-type-id": "is-referenced-by"}}
    row = parse_event(event)
    assert row["data_doi"] == "10.5285/abc"
    assert row["source_id"] == "datacite-crossref"
    # non-10.5285 subjects are dropped
    other = {"attributes": {"subj-id": "https://doi.org/10.9999/zzz",
                            "obj-id": "x"}}
    assert parse_event(other) is None


# --- doi.org CSL ------------------------------------------------------------

def test_csl_parse_full():
    data = {"title": "Paper", "publisher": "Elsevier", "type": "journal-article",
            "author": [{"given": "Ann", "family": "Smith"}],
            "created": {"date-parts": [[2020, 3, 15]]}}
    info = parse_csl(data)
    assert info["date"] == "15/3/2020"
    assert info["authors"] == [["Ann", "Smith"]]
    assert info["publisher"] == "Elsevier"          # the old data['type'] bug stays dead
    assert info["type"] == "journal-article"


def test_csl_parse_fallbacks():
    info = parse_csl({})
    assert info["title"] == "Info not given"
    assert info["authors"] == "Info not given"


# --- Overton ----------------------------------------------------------------

def test_overton_parse_document():
    doc = {"title": "Policy doc", "authors": ["Government of Canada"],
           "published_on": "2025-12-01",
           "document_url": "http://publications.gc.ca/x",
           "highlights": [{"type": "references", "doi": "10.5285/abc"}],
           "source": {"title": "Government of Canada"},
           "overton_policy_document_series": "Publication"}
    row = parse_document(doc, "10.5285/abc")
    assert row["data_doi"] == "10.5285/abc"
    assert row["pub_doi"] == "http://publications.gc.ca/x"
    assert row["relation_type"] == "references"
    assert row["pub_publisher"] == "Government of Canada"
    assert row["pub_type"] == "Publication"
