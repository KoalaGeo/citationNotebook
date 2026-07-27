"""OpenAIRE Scholexplorer v3.

Verified against the official v3 docs and a live response:
  * Relations are stored ACTIVE-voice ("A Cites B", never "B IsCitedBy A"), so
    citations OF a dataset are inbound links: query targetPid=<dataset DOI> and
    read the link's `source` (the citing work). The old v2 code queried
    sourcePid and filtered Name == "IsReferencedBy" -- wrong direction, and a
    Name v3 never returns -- which silently dropped Scholix citations (#11).
  * RelationshipType.Name is the generic "IsRelatedTo"; the real semantic is in
    SubType (e.g. "cites").
  * Pagination is 0-indexed; the server serves 10 links/page and ignores a
    `size` parameter, so we walk totalPages (with an empty-page guard because
    totals can be garbage on broad queries).
"""

from ..http import get_json, parallel_map
from ..normalize import creator_names, strip_doi_url

SCHOLIX_V3_BASE = "https://api.scholexplorer.openaire.eu/v3/Links"
MAX_PAGES = 1000


def parse_link(link, data_doi):
    """One Scholix link -> a citation row (the link's `source` is the citing work)."""
    rel = link.get("RelationshipType") or {}
    src = link.get("source") or {}

    pub_doi = None
    for scheme in ("doi", "handle", "pmid", "pmc"):
        for idinfo in src.get("Identifier") or []:
            if isinstance(idinfo, dict) and \
                    str(idinfo.get("IDScheme", "")).lower() == scheme and idinfo.get("ID"):
                pub_doi = idinfo["ID"]
                break
        if pub_doi:
            break

    publishers = src.get("Publisher") or []
    publisher = publishers[0].get("name") if publishers and isinstance(publishers[0], dict) else None

    return {
        "data_doi": data_doi,
        "pub_doi": strip_doi_url(pub_doi) if pub_doi else None,
        "source_id": "scholex",
        "relation_type": rel.get("SubType") or rel.get("Name"),
        "pub_title": src.get("Title"),
        "pub_date": src.get("PublicationDate"),
        "pub_authors": creator_names(src.get("Creator")),
        "pub_type": src.get("Type"),
        "pub_publisher": publisher,
    }


def fetch_for_doi(session, data_doi, relation=None, subtypes=None):
    """All inbound links for one dataset DOI. Per-record try/except so one
    malformed link never discards the rest of a page (a v2 failure mode)."""
    keep = {s.lower() for s in subtypes} if subtypes else None
    rows, errors, page, total_pages = [], 0, 0, 1
    while page < total_pages and page < MAX_PAGES:
        params = {"targetPid": data_doi, "page": page}
        if relation:
            params["relation"] = relation
        payload, err = get_json(session, SCHOLIX_V3_BASE, params=params)
        if err:
            print(f"[scholix] {data_doi} page {page}: {err}")
            errors += 1
            break
        total_pages = payload.get("totalPages") or 0
        results = payload.get("result") or []
        if not results:
            break
        for link in results:
            try:
                row = parse_link(link, data_doi)
                if keep is not None and \
                        str(link.get("RelationshipType", {}).get("SubType") or "").lower() not in keep:
                    continue
                if row["pub_doi"]:
                    rows.append(row)
            except Exception as exc:            # noqa: BLE001 - keep the page alive
                print(f"[scholix] skipped a link for {data_doi}: {exc}")
                errors += 1
        page += 1
    return rows, errors


def fetch_citations(session, data_dois, relation=None, subtypes=None, workers=6):
    """Inbound Scholix links for every dataset DOI (parallel across DOIs)."""
    results = parallel_map(
        lambda doi: fetch_for_doi(session, doi, relation, subtypes),
        list(data_dois), workers=workers)
    rows = [row for rws, _ in results for row in rws]
    errors = sum(errs for _, errs in results)
    return rows, errors
