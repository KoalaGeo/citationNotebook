"""OpenAIRE Scholexplorer (Scholix v3): every incoming link, with its relation kept.

Scholexplorer states links from the citing work's side ("source Cites target"),
with the dataset as target, so relations are turned round to the dataset's side.
v3 counted every relation as a citation; here each keeps its class, so
``HasAmongTopNSimilarDocuments`` (similarity recommendations, 54% of the
harvest on 7 Oct 2026) is published as a related link, never as a citation.

Requests run in parallel and each DOI is logged as it completes, so a run cut
short by the GitHub job limit resumes where it stopped (v3 took 5 h 13 min of 6 h).
"""

from __future__ import annotations

from ..harvest import RawLink, Tally, per_key
from ..ids import normalise_id
from ..relations import dataset_side, relation_class

SOURCE = "scholexplorer"
BUCKETS = ("api.scholexplorer.openaire.eu",)   # rate-limit buckets it calls (citations.http.bucket_for)
LINKS_URL = "https://api.scholexplorer.openaire.eu/v3/Links"
PAGE_SIZE = 100
SCHEME_PREFERENCE = ("doi", "pmid", "pmc", "handle", "url")


def best_identifier(identifiers, exclude: str):
    """The identifier of a citing work, from the identifiers Scholexplorer lists for it.

    Args:
        identifiers: The Scholix ``Identifier`` list (``ID``, ``IDScheme``,
            ``IDURL``).
        exclude: The dataset's DOI, which is never the citing work.

    Returns:
        ``(identifier, type)``: a DOI if it has one, else a PMID, PMC, handle or
        URL; None when nothing usable is listed.
    """
    ids = [i for i in identifiers or [] if isinstance(i, dict)]
    for scheme in SCHEME_PREFERENCE:
        for ident in ids:
            if (ident.get("IDScheme") or "").lower() == scheme:
                found = normalise_id(ident.get("ID") or ident.get("IDURL"), scheme=scheme, exclude=exclude)
                if found:
                    return found
    for ident in ids:
        found = normalise_id(ident.get("IDURL") or ident.get("ID"), exclude=exclude)
        if found:
            return found
    return None


def _hint(source: dict) -> dict:
    """What Scholexplorer says about the citing work, kept as its metadata hint.

    Args:
        source: The Scholix link's ``source`` object.

    Returns:
        ``title``, ``issued``, ``work_type``, ``publisher`` and ``authors``, with
        empty keys left out.
    """
    publishers = source.get("Publisher") or []
    hint = {
        "title": source.get("Title"),
        "issued": source.get("PublicationDate"),
        "work_type": source.get("Type"),
        "publisher": publishers[0].get("name") if publishers and isinstance(publishers[0], dict) else None,
        "authors": [{"name": c.get("name")} for c in source.get("Creator") or [] if isinstance(c, dict) and c.get("name")],
    }
    return {k: v for k, v in hint.items() if v}


def parse_link(link: dict, doi: str, tally: Tally) -> RawLink | None:
    """One Scholix link as a raw link.

    Args:
        link: One item of a Scholexplorer ``result`` list.
        doi: The dataset's DOI (the link's target).
        tally: Counts unknown relations, outgoing relations and links with no
            usable identifier.

    Returns:
        The raw link, or None when it is skipped.
    """
    rel = link.get("RelationshipType") or {}
    name, subtype = rel.get("Name") or "", rel.get("SubType") or ""
    raw = "/".join(x for x in (name, subtype) if x)
    relation = dataset_side(subtype or name, "object")
    if relation is None:
        tally.add(f"unknown_relation:{raw}")
        return None
    if relation_class(relation) is None:
        tally.add("outgoing_relation")
        return None
    source = link.get("source") or {}
    found = best_identifier(source.get("Identifier"), exclude=doi)
    if not found:
        tally.add("no_identifier")
        return None
    return RawLink(doi, found[0], found[1], relation, raw, "scholexplorer", _hint(source))


def fetch_links(client, doi: str, tally: Tally) -> list[RawLink]:
    """Every Scholexplorer link to one dataset, page by page.

    Args:
        client: The HTTP client.
        doi: The dataset's DOI.
        tally: Counts what was skipped and why.

    Returns:
        The dataset's links.

    Raises:
        citations.http.HttpError: If a page cannot be fetched.
    """
    links, page, total_pages = [], 0, 1
    while page < total_pages and page < 1000:
        payload = client.get_json(LINKS_URL, params={"targetPid": doi, "page": page, "size": PAGE_SIZE},
                                  allow_404=False)
        total_pages = payload.get("totalPages") or 0
        results = payload.get("result") or []
        if (payload.get("totalLinks") or 0) <= 0 or not results:
            break
        for link in results:
            parsed = parse_link(link, doi, tally) if isinstance(link, dict) else None
            if parsed:
                links.append(parsed)
        page += 1
    return links


def harvest(ctx, run_id: int) -> dict:
    """Harvest Scholexplorer for every dataset in the inventory.

    Args:
        ctx: The harvest context.
        run_id: The harvest run.

    Returns:
        ``{"details": {...}}`` with the tally's counts.
    """
    tally = Tally()
    dois = [row["doi"] for row in ctx.datasets()]
    per_key(ctx, SOURCE, run_id, dois, lambda doi: fetch_links(ctx.client, doi, tally))
    return {"details": tally.as_dict()}
