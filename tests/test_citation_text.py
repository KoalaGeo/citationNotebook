"""Offline tests for citations.citation_text (no network). Ported from the v3 tests."""
import pytest

from citations import citation_text as gcs

ERRORS_SEEN_IN_RESULTS = [
    "Unknown style frontiers-of-biogeography",
    "DOI exists but metadata could not be retrieved - contact info@doi.org for help with this",
    "DOI not found",
    "not a doi",
    "error occurred",
]


@pytest.mark.parametrize("value, expected", [
    ("10.1016/j.scitotenv.2012.05.023", "10.1016/j.scitotenv.2012.05.023"),
    ("https://doi.org/10.1111/1365-2656.12728", "10.1111/1365-2656.12728"),
    ("doi:10.5194/cp-2017-18", "10.5194/cp-2017-18"),
    ("https://pubs.acs.org/doi/10.1021/acs.est.9b02292", "10.1021/acs.est.9b02292"),
    ("https://iopscience.iop.org/article/10.1088/2515-7620/ab48da", "10.1088/2515-7620/ab48da"),
    ("10.1016/10.1111/jbi.13501", "10.1111/jbi.13501"),          # doubled prefix
    ("https://doi.org/10.5285%2Fabc-123", "10.5285/abc-123"),     # URL-encoded
    ("https://peerj.com/manuscripts/29426", None),
    ("https://example.org/page?ref=10.5285/abc-123", None),       # DOI only in query
    ("not a doi", None),
    (None, None),
    (float("nan"), None),
])
def test_normalise_doi(value, expected):
    """DOIs are found in bare, ``doi:``, ``doi.org``, publisher-URL, doubled-prefix and URL-encoded forms, and not in query strings or placeholders."""
    assert gcs.normalise_doi(value) == expected


def test_normalise_doi_ignores_the_cited_dataset():
    """A URL that contains the cited dataset's own DOI does not give that DOI, whatever its case."""
    assert gcs.normalise_doi("https://catalogue.example/doc/10.5285/abc", data_doi="10.5285/ABC") is None


STYLE_NOT_FOUND = ('{"code":"style-not-found","message":"Style [frontiers-of-biogeography] does not exist",'
                   '"doi":"10.1111\\/1365-2656.12728"}')
APA = ("Griffiths, H. M., Ashton, L. A., Walker, A. E., Hasan, F., Evans, T. A., Eggleton, P., & Parr, C. L. "
       "(2017). Ants are the major agents of resource removal from tropical rainforests. Journal of Animal "
       "Ecology, 87(1), 293\u2013300. Portico. https://doi.org/10.1111/1365-2656.12728")


@pytest.mark.parametrize("text", ERRORS_SEEN_IN_RESULTS + ["", None, "<html><body>503</body></html>", STYLE_NOT_FOUND])
def test_error_values_are_not_citations(text):
    """Formatter error messages, placeholders, HTML pages and JSON errors are not taken as citations."""
    assert not gcs.is_real_citation(text)


def test_real_citation_with_not_found_in_title_is_kept():
    """A real citation whose title happens to contain "not found" is still a citation."""
    text = "Smith J. (2020). Species not found in surveys of upland soils. Ecology 12, 1-9."
    assert gcs.is_real_citation(text)


@pytest.mark.parametrize("authors, expected", [
    ("[['N.A.', 'Beresford'], ['C.L.', 'Barnett'], ['J.', 'Vives i Batlle'], ['E.D.', 'Potter']]",
     "Beresford N.A., Barnett C.L., Vives i Batlle J., et al."),
    ("['Bentley, L.', 'Reinsch, S.']", "Bentley, L., Reinsch, S."),
    ("['Joint Nature Conservation Committee']", "Joint Nature Conservation Committee"),
    ("[['Government of Northwest Territories']]", "Government of Northwest Territories"),
    ("Info not given", ""),
    ("not a doi", ""),
])
def test_authors(authors, expected):
    """Author lists in v3's formats become a short list with initials and ``et al.``; placeholders become empty."""
    assert gcs._authors(authors) == expected


def test_fallback_for_url_identified_work():
    """A work with no DOI gets a citation from its metadata, naming an organisation that is author and publisher once."""
    row = {"pub_title": "Scoping the use of predictive models", "pub_authors": "['Joint Nature Conservation Committee']",
           "publicationYear": "2019", "pub_publisher": "Joint Nature Conservation Committee"}
    # An organisation that is both author and publisher is named once.
    assert gcs.fallback_citation(row) == (
        "Joint Nature Conservation Committee (2019). Scoping the use of predictive models."
    )


def test_fallback_with_doi_and_date_only():
    """A fallback citation takes its year from a D/M/YYYY date and ends with the DOI link."""
    row = {"pub_title": "Ants are the major agents.", "pub_authors": "[['Hannah M.', 'Griffiths']]",
           "publicationYear": None, "pub_date": "9/8/2017", "pub_publisher": "Wiley"}
    assert gcs.fallback_citation(row, "10.1111/1365-2656.12728") == (
        "Griffiths H.M. (2017). Ants are the major agents. Wiley. https://doi.org/10.1111/1365-2656.12728"
    )


def test_fallback_without_title_is_empty():
    """Without a title there is no fallback citation."""
    row = {"pub_title": "not a doi", "pub_authors": "not a doi", "pub_publisher": "not a doi"}
    assert gcs.fallback_citation(row) == ""


class FakeResponse:
    """A minimal HTTP response: a status code and a body."""

    def __init__(self, status, text):
        """Create the response.

        Args:
            status: The HTTP status code.
            text: The body.
        """
        self.status_code, self.text, self.encoding = status, text, None


class FakeSession:
    """Answers like the formatter: a fixed body per DOI, else the error seen since Feb 2026."""

    def __init__(self, good):
        """Create the session.

        Args:
            good: ``{doi: citation}`` for the DOIs the formatter can format.
        """
        self.good, self.calls = good, []

    def get(self, url, headers=None, timeout=None):
        """Answer a content-negotiation request, recording the DOI asked for.

        Args:
            url: The ``doi.org`` URL.
            headers: Ignored.
            timeout: Ignored.

        Returns:
            A 200 response with the DOI's citation, or with the "Unknown style"
            error the formatter returned from February 2026.
        """
        doi = url.split("doi.org/", 1)[1]
        self.calls.append(doi)
        if doi in self.good:
            return FakeResponse(200, self.good[doi])
        return FakeResponse(200, "Unknown style frontiers-of-biogeography")


def frame(rows):
    """Citation rows from tuples, in the column order v3's tests used.

    Args:
        rows: Tuples of ``data_doi``, ``pub_doi``, ``pub_title``,
            ``pub_authors``, ``publicationYear``, ``pub_date`` and
            ``pub_publisher``.

    Returns:
        A list of row dicts.
    """
    cols = ["data_doi", "pub_doi", "pub_title", "pub_authors", "publicationYear", "pub_date", "pub_publisher"]
    return [dict(zip(cols, r)) for r in rows]


def run(rows, previous=None, **kwargs):
    """`citations.citation_text.format_citations` with the v3 tests' "previous results" shape.

    Args:
        rows: The citation rows.
        previous: ``{publication DOI or URL: citation}`` from last week's
            results, as the v3 tests gave it.
        **kwargs: Passed on to ``format_citations``; ``pause`` defaults to 0.

    Returns:
        The citation strings only.
    """
    reuse = {}
    for doi_value, text in (previous or {}).items():
        doi = gcs.normalise_doi(doi_value)
        if doi:
            reuse[doi.lower()] = text
    kwargs.setdefault("pause", 0)
    strings, _sources, _stats = gcs.format_citations(rows, reuse=reuse, **kwargs)
    return strings


GOOD = "Griffiths, H. M., et al. (2017). Ants are the major agents of resource removal. J. Anim. Ecol."


def test_end_to_end(monkeypatch):
    """Formatted, reused, fallback and empty citations in one run, each DOI looked up once and no error text in the output."""
    session = FakeSession({"10.1111/1365-2656.12728": GOOD})
    monkeypatch.setattr(gcs, "_session", lambda: session)
    df = frame([
        ("10.5285/d1", "10.1111/1365-2656.12728", "Ants", "[]", "2017", "", "Wiley"),
        ("10.5285/d2", "10.1111/1365-2656.12728", "Ants", "[]", "2017", "", "Wiley"),    # same pub: one lookup
        ("10.5285/d1", "10.1016/j.x.2020.1", "A failing DOI", "['Smith, J.']", "2020", "", "Elsevier"),
        ("10.5285/d1", "https://example.org/report", "A policy report", "['Some Agency']", "2021", "", "Some Agency"),
        ("10.5285/d1", "https://peerj.com/m/1", "not a doi", "not a doi", None, "Info not given", "not a doi"),
        ("10.5285/d3", "10.5194/reused", "Reused", "[]", "2019", "", "Copernicus"),
    ])
    previous = {"10.5194/reused": "Prior, A. (2019). A citation kept from last week. Copernicus.",
                "10.1016/j.x.2020.1": "Unknown style frontiers-of-biogeography"}
    s = run(df, previous, min_success_rate=None)
    assert s[0] == GOOD and s[1] == GOOD
    assert s[2] == "Smith, J. (2020). A failing DOI. Elsevier. https://doi.org/10.1016/j.x.2020.1"
    assert s[3] == "Some Agency (2021). A policy report."
    assert s[4] == ""
    assert s[5] == "Prior, A. (2019). A citation kept from last week. Copernicus."
    assert not any(e in x for x in s for e in ERRORS_SEEN_IN_RESULTS if e)
    assert sorted(session.calls) == ["10.1016/j.x.2020.1", "10.1111/1365-2656.12728"]


def test_raises_when_formatter_is_broken(monkeypatch):
    """When none of 25 lookups gives a citation, formatting raises rather than writing degraded strings."""
    monkeypatch.setattr(gcs, "_session", lambda: FakeSession({}))
    df = frame([("10.5285/d", f"10.1000/{i}", "T", "[]", "2020", "", "P") for i in range(25)])
    with pytest.raises(RuntimeError, match="0 of 25"):
        run(df)


def test_real_doi_org_apa_response_is_accepted():
    # Verbatim response from doi.org content negotiation, 2026-10-05.
    """A verbatim APA citation from ``doi.org`` is accepted as a real citation."""
    assert gcs.is_real_citation(APA)


def test_requests_apa_by_default(monkeypatch):
    """Citations are requested as APA in British English by default, and the response is used as it is."""
    seen = {}

    class Session:
        """A session that records the Accept header and answers with an APA citation."""

        def get(self, url, headers=None, timeout=None):
            """Record the Accept header and return the APA citation."""
            seen["accept"] = headers["Accept"]
            return FakeResponse(200, APA)

    monkeypatch.setattr(gcs, "_session", lambda: Session())
    out = run(frame([("10.5285/d", "10.1111/1365-2656.12728", "Ants", "[]", "2017", "", "Wiley")]),
              min_success_rate=None)
    assert seen["accept"] == "text/x-bibliography; style=apa; locale=en-GB"
    assert out[0] == APA


def test_style_not_found_falls_back_even_with_http_200(monkeypatch):
    """A "style not found" JSON error sent with HTTP 200 is not used; the citation falls back to the metadata."""
    class Session:
        """A session that answers every request with the "style not found" error."""

        def get(self, url, headers=None, timeout=None):
            """Return the "style not found" error with HTTP 200."""
            return FakeResponse(200, STYLE_NOT_FOUND)

    monkeypatch.setattr(gcs, "_session", lambda: Session())
    out = run(frame([("10.5285/d", "10.1111/x", "Ants", "['Griffiths, H.']", "2017", "", "Wiley")]),
              min_success_rate=None)
    assert out[0] == "Griffiths, H. (2017). Ants. Wiley. https://doi.org/10.1111/x"


# --- plain text: markup, entities and line breaks (Oct 2026 results) -----------------

@pytest.mark.parametrize("raw, expected", [
    # Crossref title with JATS italics and line breaks (broke CSV viewers)
    ("Absence of\n                    <i>Wolbachia</i>\n                    in <i>Eretmoptera murphyi</i>\n"
     "                    (Diptera: Chironomidae). Antarctic Science",
     "Absence of Wolbachia in Eretmoptera murphyi (Diptera: Chironomidae). Antarctic Science"),
    # DataCite formatter output: italic title and &amp;
    ("Jones, J., &amp; Hubbard, B. (2019). <i>Point cloud data</i> (Version 1.0) [Data set].",
     "Jones, J., & Hubbard, B. (2019). Point cloud data (Version 1.0) [Data set]."),
    ("Environmental Science &Amp; Technology", "Environmental Science & Technology"),  # Crossref title-casing
    ("A &amp;amp; B", "A & B"),                                                          # double-escaped
    ("soil N <sub>2</sub> O emission", "soil N₂O emission"),
    ("CO <sub>2</sub> emissions", "CO₂ emissions"),
    ("using <sup>137</sup>Cs to", "using ¹³⁷Cs to"),
    ("Ca<sup>2+</sup> ions", "Ca²⁺ ions"),
    ("an area of 5 m <sup>2</sup>.", "an area of 5 m²."),
    ("Has <scp>S</scp>cots pine", "Has Scots pine"),
    ("p &lt; 0.05", "p < 0.05"),
    ("<S1-11> Effect of through-fall exclusion", "<S1-11> Effect of through-fall exclusion"),  # not markup
    ("x<sup>a</sup> note", "xa note"),
    (None, ""),
])
def test_plain_text(raw, expected):
    """Markup, entities, sub- and superscripts and line breaks become plain text; text that only looks like a tag is kept."""
    assert gcs.plain_text(raw) == expected


def test_every_output_is_plain_text(monkeypatch):
    """Formatted, reused and fallback citations all come out as plain text."""
    marked_up = "Kamintzis, J., &amp; Hubbard, B. (2019). <i>Point cloud data\n of a channel</i>. NERC EDS."

    class Session:
        """A session that answers every request with a marked-up citation."""

        def get(self, url, headers=None, timeout=None):
            """Return the marked-up citation."""
            return FakeResponse(200, marked_up)

    monkeypatch.setattr(gcs, "_session", lambda: Session())
    df = frame([
        ("10.5285/d", "10.5285/fetched", "T", "[]", "2019", "", "P"),                 # formatted
        ("10.5285/d", "10.5285/reused", "T", "[]", "2019", "", "P"),                  # reused from last run
        ("10.5285/d", "https://x.org/r", "Fish (<i>Salmo</i>)\n study", "[]", "2020", "", "Agency"),  # fallback
    ])
    out = run(df, {"10.5285/reused": marked_up}, min_success_rate=None)
    clean = "Kamintzis, J., & Hubbard, B. (2019). Point cloud data of a channel. NERC EDS."
    assert out == [clean, clean, "(2020). Fish (Salmo) study. Agency."]