from citations.normalize import (creator_names, merge_publication_types,
                                 normalize_publisher, pub_year_splitter,
                                 strip_doi_url)


def test_strip_doi_url():
    assert strip_doi_url("https://doi.org/10.1/x") == "10.1/x"
    assert strip_doi_url("https://dx.doi.org/10.1/x") == "10.1/x"
    assert strip_doi_url("10.1/x") == "10.1/x"
    assert strip_doi_url("http://publications.gc.ca/x") == "http://publications.gc.ca/x"
    assert strip_doi_url(None) is None


def test_normalize_publisher():
    assert normalize_publisher("British Oceanographic Data Centre") == \
        "British Oceanographic Data Centre (BODC)"
    assert normalize_publisher("NERC EDS National Geoscience Data Centre") == \
        "National Geoscience Data Centre (NGDC)"
    assert normalize_publisher("UK Polar Data Centre") == "Polar Data Centre (PDC)"
    assert normalize_publisher("Centre for Environmental Data Analysis") == \
        "Centre for Environmental Data Analysis (CEDA)"
    assert normalize_publisher("Someone Else") == "Someone Else"
    assert normalize_publisher(None) is None


def test_pub_year_splitter():
    assert pub_year_splitter("15/3/2021") == "2021"     # doi.org d/m/Y
    assert pub_year_splitter("2025-12-01") == "2025"    # scholix/overton ISO
    assert pub_year_splitter("Info not given") is None
    assert pub_year_splitter(None) is None


def test_merge_publication_types():
    assert merge_publication_types("literature", "journal-article") == "journal-article"
    assert merge_publication_types("unknown", "report") == "report"
    assert merge_publication_types("journal-article", "not a doi") == "journal-article"
    assert merge_publication_types("dataset", "book-chapter") == "book-chapter"
    assert merge_publication_types("a", "a") == "a"
    assert merge_publication_types("x", "y") == "y"     # default: doi.org wins


def test_creator_names():
    assert creator_names([{"name": "A"}, {"name": "B", "identifier": []}]) == ["A", "B"]
    assert creator_names(None) == []
