"""doi.org lookups: publication metadata (CSL content negotiation), a
registry fallback for the publication type, and formatted citation strings.

Ports getPublicationInfo_forDataCite.py, getPublicationType_forScholex.py and
getCitationString.py (with their reviewed fixes) into one module with ONE
cacheable lookup per publication DOI -- the old pipeline resolved the same DOI
against doi.org in two separate passes (metadata for DataCite rows, type for
Scholix rows), which is why those steps took hours.
"""

from requests.exceptions import RequestException

from ..http import get_json

FAILED = "API request failed"
NOT_GIVEN = "Info not given"
NOT_A_DOI = "not a doi"

CITATION_STYLE_URL = ("https://citation.doi.org/format"
                      "?style=frontiers-of-biogeography&lang=en-GB&doi=")


def _format_date(pub_date):
    """CSL created.date-parts [[Y, M, D]] -> 'D/M/Y'; anything else passes through."""
    try:
        return f"{pub_date[0][2]}/{pub_date[0][1]}/{pub_date[0][0]}"
    except (TypeError, IndexError, KeyError):
        return pub_date


def parse_csl(data):
    """CSL JSON -> the pub_info fields, with the old pipeline's fallbacks."""
    title = data.get("title", NOT_GIVEN)

    author = data.get("author")
    if isinstance(author, list):
        try:
            authors = [[a["given"], a["family"]] for a in author]
        except (TypeError, KeyError):
            authors = author
    elif author is not None:
        authors = author
    else:
        authors = NOT_GIVEN

    pub_date = data.get("created", {})
    if isinstance(pub_date, dict):
        pub_date = pub_date.get("date-parts", data.get("created", NOT_GIVEN))
    if pub_date in ({}, None):
        pub_date = data.get("published", NOT_GIVEN)

    return {
        "title": title,
        "date": _format_date(pub_date),
        "authors": authors,
        "publisher": data.get("publisher", NOT_GIVEN),
        "type": data.get("type", NOT_GIVEN),
    }


def registry_type(session, pub_doi):
    """When CSL fails, ask which registry owns the DOI and query it for a type.
    Ported from getPublicationType_forScholex's fallback path."""
    payload, err = get_json(session, "https://doi.org/doiRA/" + pub_doi,
                            headers={"Accept": "application/json"})
    if err or not isinstance(payload, list) or not payload:
        return None
    registry = payload[0].get("RA")
    if registry == "DataCite":
        data, err = get_json(session, "https://api.datacite.org/dois/" + pub_doi,
                             headers={"client-id": "bl.nerc"})
        if not err:
            try:
                return data["data"]["attributes"]["types"]["citeproc"]
            except (KeyError, TypeError):
                return None
    elif registry == "Crossref":
        data, err = get_json(session, "https://api.crossref.org/works/" + pub_doi,
                             headers={"Accept": "application/json"})
        if not err:
            try:
                return data["message"]["type"]
            except (KeyError, TypeError):
                return None
    return None


def fetch_pub_info(session, pub_doi):
    """Resolve one publication DOI to {title, date, authors, publisher, type}."""
    if not isinstance(pub_doi, str) or not pub_doi.startswith("10."):
        return {"title": NOT_A_DOI, "date": NOT_GIVEN, "authors": NOT_A_DOI,
                "publisher": NOT_A_DOI, "type": NOT_A_DOI}
    payload, err = get_json(session, "https://doi.org/" + pub_doi,
                            headers={"Accept": "application/json"})
    if err and "request error" in err:
        return {"title": FAILED, "date": FAILED, "authors": FAILED,
                "publisher": FAILED, "type": FAILED}
    if err or not isinstance(payload, dict):
        # Resolved but not CSL JSON: try the registry for at least the type.
        rtype = registry_type(session, pub_doi)
        return {"title": NOT_GIVEN, "date": NOT_GIVEN, "authors": NOT_GIVEN,
                "publisher": NOT_GIVEN, "type": rtype or "unknown"}
    info = parse_csl(payload)
    if info["type"] in (NOT_GIVEN, None):
        info["type"] = registry_type(session, pub_doi) or info["type"]
    return info


def fetch_citation_string(session, pub_doi, timeout=10):
    """One formatted citation string from citation.doi.org.

    Keeps the #17 fix: the formatter returns UTF-8 but often omits the charset,
    and requests then defaults text/* to ISO-8859-1. Forcing UTF-8 handles both
    the Muller-with-umlaut mojibake AND en-dash page ranges; the old
    .encode('latin1').decode('utf-8') round-trip crashed on the latter.
    """
    if not isinstance(pub_doi, str) or not pub_doi.startswith("10."):
        return NOT_A_DOI
    try:
        r = session.get(CITATION_STYLE_URL + pub_doi,
                        headers={"Accept": "text/x-bibliography",
                                 "Accept-Charset": "utf-8"},
                        timeout=timeout)
        if r.status_code != 200:
            return "error occurred"
        r.encoding = "utf-8"
        return r.text
    except RequestException:
        return "error occurred"
