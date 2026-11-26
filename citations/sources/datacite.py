"""DataCite: the citations DataCite itself counts, labelled from its events, plus links in dataset metadata.

v3 asked the events API only for is-cited-by, is-referenced-by and
is-supplement-to with the dataset as subject. Citations from journal
reference lists are deposited by Crossref as ``references`` events with the
*article* as subject and the dataset as object, so v3 never saw them (99% of
the missing links in the 7 Oct 2026 check). This module instead:

1. takes, for every dataset DataCite counts as cited, the record's
   ``relationships.citations`` - the exact list behind ``citationCount``. The
   bulk ``/dois`` listing does not carry it, so this is one request per cited
   dataset;
2. labels each of those links from ``/events?doi=`` (event source and
   relation, turned round to the dataset's side);
3. adds every incoming relation the data centre wrote into the dataset's own
   ``relatedIdentifiers`` (already downloaded with the inventory, so no requests).
"""

from __future__ import annotations

from urllib.parse import quote

from ..harvest import RawLink, Tally, log_fetch, per_key, write_links
from ..ids import normalise_id
from ..relations import dataset_side, is_incoming, relation_class

SOURCE = "datacite"
BUCKETS = ("api.datacite.org",)   # rate-limit buckets it calls (citations.http.bucket_for)
RECORD_URL = "https://api.datacite.org/dois/{doi}"
EVENTS_URL = "https://api.datacite.org/events"

# Event relation types DataCite counts as citations.
CITATION_EVENT_TYPES = {"cites", "is-cited-by", "references", "is-referenced-by", "is-supplement-to", "is-supplemented-by"}
# Event sources that are DataCite's copies of relatedIdentifiers in DataCite metadata.
METADATA_EVENT_SOURCES = {"datacite-crossref", "datacite-related", "datacite-url", "datacite-kisti",
                          "datacite-medra", "datacite-op", "datacite-istic", "datacite-jalc", "datacite-airiti"}
RELATED_TYPES = {"DOI": "doi", "URL": "url", "HANDLE": "handle", "PMID": "pmid"}


def _event_doi(value):
    """The DOI of an event's subject or object.

    Args:
        value: An event's ``subj-id`` or ``obj-id``, usually a ``doi.org`` URL.

    Returns:
        The bare lower-case DOI, or None when it is not a DOI.
    """
    found = normalise_id(value)
    return found[0] if found and found[1] == "doi" else None


def provenance_of(event_source: str | None) -> str:
    """A raw link's provenance from the DataCite event source that stated it.

    Args:
        event_source: The event's ``source-id``, or None when no event labelled
            the link.

    Returns:
        ``"datacite"`` when there is no event, ``"metadata"`` for DataCite's
        copies of ``relatedIdentifiers``, else the event source itself (for
        example ``"crossref"`` for Crossref reference lists).
    """
    if not event_source:
        return "datacite"
    if event_source in METADATA_EVENT_SOURCES:
        return "metadata"
    return event_source  # e.g. "crossref": Crossref reference lists


def event_labels(client, doi: str) -> dict:
    """How each citing work's link to a dataset is stated in the DataCite events.

    Only event relation types DataCite counts as citations
    (`CITATION_EVENT_TYPES`) are read. Where a work has several events, one
    that reads as an incoming relation from the dataset's side wins.

    Args:
        client: The HTTP client.
        doi: The dataset's DOI.

    Returns:
        ``{citing_id: (dataset_relation, raw_relation, side, event_source)}``,
        where `side` is ``"subject"`` or ``"object"``: where the dataset sat in
        the event.

    Raises:
        citations.http.HttpError: If a page of events cannot be fetched.
    """
    labels, url, params = {}, EVENTS_URL, {"doi": doi, "page[size]": 1000}
    for _ in range(50):
        page = client.get_json(url, params=params, allow_404=False)
        for event in page.get("data") or []:
            a = event.get("attributes") or {}
            rel = (a.get("relation-type-id") or "").lower()
            if rel not in CITATION_EVENT_TYPES:
                continue
            subj, obj = _event_doi(a.get("subj-id")), _event_doi(a.get("obj-id"))
            if subj == doi and obj:
                other, side = obj, "subject"
            elif obj == doi and subj:
                other, side = subj, "object"
            else:
                continue
            label = (dataset_side(rel, side), rel, side, a.get("source-id"))
            # Prefer a label that reads as an incoming relation.
            if other not in labels or (not is_incoming(labels[other][0]) and is_incoming(label[0])):
                labels[other] = label
        url = (page.get("links") or {}).get("next")
        params = None
        if not url or not page.get("data"):
            break
    return labels


def fetch_cited(client, doi: str, tally: Tally) -> list[RawLink]:
    """The links behind one dataset's DataCite ``citationCount``.

    Reads ``relationships.citations`` from the dataset's record, then labels
    each citing work from `event_labels`. A work DataCite counts but no
    event states as incoming is kept as ``IsCitedBy``: DataCite's verdict is
    kept, and what the event said is recorded in ``source_relation``.

    Args:
        client: The HTTP client.
        doi: The dataset's DOI.
        tally: Counts records not found, citation lists that differ from the
            count, and links with no incoming label.

    Returns:
        The dataset's links; empty when DataCite has no record for it.

    Raises:
        citations.http.HttpError: If the record or events cannot be fetched.
    """
    record = client.get_json(RECORD_URL.format(doi=quote(doi, safe="/")), allow_404=True)
    if record is None:
        tally.add("record_not_found")
        return []
    data = record.get("data") or {}
    cited_by = ((data.get("relationships") or {}).get("citations") or {}).get("data") or []
    count = int((data.get("attributes") or {}).get("citationCount") or 0)
    citing = []
    for item in cited_by:
        found = normalise_id(item.get("id"), exclude=doi)
        if found:
            citing.append(found)
    if len(citing) != count:
        tally.add("citation_list_differs_from_count")
    labels = event_labels(client, doi) if citing else {}

    links = []
    for citing_id, kind in citing:
        label = labels.get(citing_id)
        if label and is_incoming(label[0]):
            relation, raw = label[0], f"citations:{label[1]}:{label[2]}"
            provenance = provenance_of(label[3])
        else:
            # DataCite counts it as a citation, but no event states it as one from the
            # dataset's side (seen for some dataset-to-dataset links). Keep DataCite's
            # verdict and record what the event said, for audit.
            relation = "IsCitedBy"
            raw = f"citations:{label[1]}:{label[2]}" if label else "citations"
            provenance = provenance_of(label[3]) if label else "datacite"
            tally.add("unlabelled_citation" if not label else "citation_with_outgoing_event")
        links.append(RawLink(doi, citing_id, kind, relation, raw, provenance))
    return links


def metadata_links(datasets, relations, tally: Tally) -> list[RawLink]:
    """Incoming relations from the datasets' own ``relatedIdentifiers``.

    These were downloaded with the inventory, so no requests are made.
    Outgoing relations, unsupported identifier types and identifiers that
    cannot be parsed are counted and skipped.

    Args:
        datasets: The inventory's ``datasets`` rows.
        relations: The ``dataset_relations`` rows.
        tally: Counts what was skipped and why.

    Returns:
        One link per usable incoming relation, with provenance ``metadata``.
    """
    known = {row["doi"] for row in datasets}
    links = []
    for rel in relations:
        doi = rel["doi"]
        if doi not in known:
            continue
        kind = RELATED_TYPES.get((rel["related_type"] or "").upper())
        if kind is None:
            tally.add(f"metadata_unsupported_type:{rel['related_type']}")
            continue
        relation = dataset_side(rel["relation_type"], "subject")
        if relation_class(relation) is None:
            tally.add("metadata_outgoing_or_unknown")
            continue
        found = normalise_id(rel["related_raw"], scheme=kind, exclude=doi)
        if not found:
            tally.add("metadata_unparseable_identifier")
            continue
        links.append(RawLink(doi, found[0], found[1], relation, rel["relation_type"], "metadata"))
    return links


def harvest(ctx, run_id: int) -> dict:
    """Harvest DataCite: dataset metadata relations, then the citations of every cited dataset.

    Args:
        ctx: The harvest context.
        run_id: The harvest run.

    Returns:
        ``{"details": {...}}`` with ``cited_datasets``, ``metadata_links`` and
        the tally's counts.
    """
    con, client = ctx.con, ctx.client
    tally = Tally()
    datasets = ctx.datasets()

    relations = con.execute("SELECT * FROM dataset_relations").fetchall()
    links = metadata_links(datasets, relations, tally)
    write_links(con, SOURCE, run_id, links)
    log_fetch(con, SOURCE, run_id, "relatedIdentifiers", "ok", n=len(links))
    con.commit()

    cited = [row["doi"] for row in datasets if (row["datacite_citation_count"] or 0) > 0]
    per_key(ctx, SOURCE, run_id, cited, lambda doi: fetch_cited(client, doi, tally))
    return {"details": {"cited_datasets": len(cited), "metadata_links": len(links), **tally.as_dict()}}
