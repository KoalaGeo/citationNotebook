"""DataCite: the NERC dataset list (/dois) and citation events (/events).

Ported from getNERCDataDOIs.py and getDataCiteCitations_relationTypes.py.
Payload parsing is split from fetching so it can be unit-tested on fixtures.
"""

from ..http import get_json
from ..normalize import normalize_publisher, strip_doi_url

DOIS_URL = "https://api.datacite.org/dois"
EVENTS_URL = "https://api.datacite.org/events"

# https://support.datacite.org/docs/connecting-to-works#summary-of-all-relationtypes
RELATION_TYPES = ["is-cited-by", "is-referenced-by", "is-supplement-to",
                  "IsPartOf", "IsContinuedBy", "IsDescribedBy",
                  "IsDocumentedBy", "IsDerivedFrom", "IsRequiredBy"]

MAX_PAGES = 1000  # safety cap on any pagination loop


def parse_dataset_record(record):
    """One /dois record -> a datasets-table row."""
    attrs = record.get("attributes") or {}
    titles = attrs.get("titles") or []
    title = titles[0].get("title", "No title given") if titles and isinstance(titles[0], dict) \
        else "No title given"
    creators = [c.get("name", "") for c in (attrs.get("creators") or [])
                if isinstance(c, dict)]
    year = attrs.get("publicationYear")
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = None
    publisher = attrs.get("publisher")
    if isinstance(publisher, dict):          # newer DataCite schema variant
        publisher = publisher.get("name")
    return {
        "data_doi": attrs.get("doi", ""),
        "publisher": normalize_publisher(publisher),
        "title": title,
        "publication_year": year,
        "authors": creators,
    }


def fetch_datasets(session, client_id="bl.nerc", page_size=1000, limit=None):
    """All datasets registered under the NERC DataCite client."""
    records, errors = [], 0
    params = {"client-id": client_id, "page[size]": page_size}
    url, use_params = DOIS_URL, params
    for _ in range(MAX_PAGES):
        payload, err = get_json(session, url, params=use_params,
                                headers={"Accept": "application/json"})
        if err:
            print(f"[datacite/dois] {err} at {url}")
            errors += 1
            break
        for record in payload.get("data") or []:
            row = parse_dataset_record(record)
            if row["data_doi"]:
                records.append(row)
        if limit and len(records) >= limit:
            return records[:limit], errors
        url = (payload.get("links") or {}).get("next")
        use_params = None                     # `next` already carries the query
        if not url:
            break
    return records, errors


def parse_event(event):
    """One /events record -> a citation row (or None if not a 10.5285 dataset)."""
    attrs = event.get("attributes") or {}
    data_doi = strip_doi_url(attrs.get("subj-id") or "")
    if not data_doi.startswith("10.5285"):
        return None
    return {
        "data_doi": data_doi,
        "pub_doi": attrs.get("obj-id") or "",   # left as URL; enrich strips it
        "source_id": attrs.get("source-id") or "datacite",
        "relation_type": attrs.get("relation-type-id"),
    }


def fetch_events(session, relation_types=None, page_size=1000):
    """Citation events for the 10.5285 prefix, across the relation types the
    old pipeline queried. Returns raw rows; publication metadata is added later
    by the doi.org enrichment step."""
    rows, errors = [], 0
    for relation_type in relation_types or RELATION_TYPES:
        params = {"prefix": "10.5285", "page[size]": page_size,
                  "relation-type-id": relation_type, "page[cursor]": "1"}
        url, use_params = EVENTS_URL, params
        for _ in range(MAX_PAGES):
            payload, err = get_json(session, url, params=use_params)
            if err:
                print(f"[datacite/events] {relation_type}: {err}")
                errors += 1
                break
            for event in payload.get("data") or []:
                row = parse_event(event)
                if row:
                    rows.append(row)
            url = (payload.get("links") or {}).get("next")
            use_params = None
            if not url:
                break
    return rows, errors
