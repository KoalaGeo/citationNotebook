"""Overton: policy documents citing NERC datasets, one link per cited dataset.

v3 read only the first highlight of each document (``x[0]``), so a document
citing several NERC datasets credited one; every highlight is used here. The
API key comes from the OVERTON_API_KEY environment variable (a repository
secret), never from the code: the key committed in v3 should be rotated.
"""

from __future__ import annotations

import logging

from ..harvest import RawLink, SourceSkipped, Tally, log_fetch, write_links
from ..ids import normalise_doi, normalise_id

log = logging.getLogger(__name__)

SOURCE = "overton"
BUCKETS = ("app.overton.io",)   # rate-limit buckets it calls (citations.http.bucket_for)
SET_URL = "https://app.overton.io/generate_id_set.php"
DOCUMENTS_URL = "https://app.overton.io/documents.php"


def _hint(doc: dict) -> dict:
    """What an Overton document says about itself, kept as the work's metadata hint.

    Args:
        doc: One Overton document.

    Returns:
        ``title``, ``issued``, ``work_type`` (the document series),
        ``publisher`` (the policy source) and ``authors``, with empty keys left
        out.
    """
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    authors = doc.get("authors") or []
    hint = {
        "title": doc.get("title"),
        "issued": doc.get("published_on"),
        "work_type": doc.get("overton_policy_document_series") or "policy-document",
        "publisher": source.get("title"),
        "authors": [{"name": a} if isinstance(a, str) else {"name": a.get("name")} for a in authors
                    if (isinstance(a, str) and a) or (isinstance(a, dict) and a.get("name"))],
    }
    return {k: v for k, v in hint.items() if v}


def parse_document(doc: dict, known: set, tally: Tally) -> list[RawLink]:
    """The links from one Overton document: one per NERC dataset it cites.

    Every highlight is read, not just the first, so a document citing several
    datasets credits each of them.

    Args:
        doc: One Overton document.
        known: The inventory's DOIs; highlights of other DOIs are counted and
            skipped.
        tally: Counts documents with no URL, highlights outside the inventory,
            and documents citing several datasets.

    Returns:
        The document's links, with the document URL as the citing identifier.
    """
    citing = normalise_id(doc.get("document_url"))
    if not citing:
        tally.add("no_document_url")
        return []
    hint = _hint(doc)
    links, seen = [], set()
    for highlight in doc.get("highlights") or []:
        if not isinstance(highlight, dict):
            continue
        doi = normalise_doi(highlight.get("doi"))
        if not doi or doi in seen:
            continue
        if doi not in known:
            tally.add("highlight_not_in_inventory")
            continue
        seen.add(doi)
        raw = highlight.get("type") or "references"
        links.append(RawLink(doi, citing[0], citing[1], "IsReferencedBy", raw, "overton", hint))
    if len(links) > 1:
        tally.add("documents_citing_several_datasets")
    return links


def harvest(ctx, run_id: int) -> dict:
    """Harvest Overton: every policy document citing a dataset in the inventory.

    Uploads the inventory's DOIs as an Overton DOI set, then pages through the
    documents that cite them, storing each page's links as it arrives.

    Args:
        ctx: The harvest context.
        run_id: The harvest run.

    Returns:
        ``{"details": {...}}`` with ``documents`` and the tally's counts.

    Raises:
        citations.harvest.SourceSkipped: If ``OVERTON_API_KEY`` is not set.
        RuntimeError: If Overton did not create the DOI set.
    """
    key = ctx.settings.overton_api_key
    if not key:
        raise SourceSkipped("OVERTON_API_KEY is not set")
    client, tally = ctx.client, Tally()
    known = ctx.dataset_dois()

    created = client.post_json(f"{SET_URL}?format=json&api_key={key}",
                               data={"dois": "\n".join(sorted(known))},
                               headers={"Content-Type": "application/x-www-form-urlencoded"})
    if "set" not in created:
        raise RuntimeError(f"Overton did not create a DOI set: {created.get('error') or created.get('warnings')}")
    url = f"{DOCUMENTS_URL}?plain_dois_cited={created['set']}&format=json&api_key={key}"

    documents = 0
    for page_number in range(1, 10000):
        page = client.get_json(url, allow_404=False)
        results = page.get("results") or []
        links = [link for doc in results if isinstance(doc, dict) for link in parse_document(doc, known, tally)]
        write_links(ctx.con, SOURCE, run_id, links)
        log_fetch(ctx.con, SOURCE, run_id, f"page:{page_number}", "ok", n=len(links))
        ctx.con.commit()
        documents += len(results)
        query = page.get("query") or {}
        log.info("overton: page %s of %s", query.get("current_page", page_number), query.get("pages", "?"))
        url = query.get("next_page_url")
        if not url:
            break
    return {"details": {"documents": documents, **tally.as_dict()}}
