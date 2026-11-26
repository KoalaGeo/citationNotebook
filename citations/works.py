"""Citing-work metadata and citation strings, cached in SQLite.

v3 took publication dates from Crossref's ``created`` (DOI registration) and
wrote them as D/M/YYYY; it fetched nothing for citing works registered with
DataCite, and repeated every lookup every week. Here each work is fetched once
(refreshed after ``works_refresh_days``), dates are the ``issued`` date in ISO
8601 with their precision, and DataCite-registered works get metadata too.

Every work's metadata is a dict with the same keys, whichever function made
it: ``title``, ``work_type`` (a Crossref type), ``container_title``,
``publisher``, ``issued``, ``issued_precision``, ``authors`` (a list of
``{given, family, name, orcid}``) and ``metadata_source``.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter
from urllib.parse import quote

from . import db
from .citation_text import format_citations, is_real_citation
from .ids import normalise_id, work_url
from .worktypes import crossref_type, datacite_type

log = logging.getLogger(__name__)

CROSSREF_WORK = "https://api.crossref.org/works/{doi}"
DATACITE_WORK = "https://api.datacite.org/dois/{doi}"
# Prefixes registered with DataCite: skip the Crossref attempt.
DATACITE_PREFIXES = ("10.5285/", "10.5281/", "10.6084/", "10.5061/", "10.1594/", "10.15468/", "10.17605/",
                     "10.48420/", "10.5880/", "10.4121/", "10.7910/", "10.25739/", "10.17863/", "10.14469/")
HINT_PRIORITY = ("scholexplorer", "overton", "crossref", "datacite")
SAVE_EVERY = 500   # works saved per transaction while fetching
WORKS_BUCKETS = ("api.crossref.org/single", "api.datacite.org", "doi.org/crossref", "doi.org/datacite")


def _agency_bucket(work) -> str:
    """The rate limit a DOI's citation string counts against.

    ``doi.org`` passes a content-negotiation request on to the DOI's
    registration agency, so the request counts against that agency's limit.

    Args:
        work: A ``works`` row.

    Returns:
        ``"doi.org/datacite"`` for a DataCite-registered DOI, else
        ``"doi.org/crossref"``.
    """
    if work["metadata_source"] in ("datacite", "inventory") or str(work["citing_id"]).startswith(DATACITE_PREFIXES):
        return "doi.org/datacite"
    return "doi.org/crossref"


def _date(parts) -> tuple[str | None, str | None]:
    """An ISO date and its precision from Crossref ``date-parts``.

    Args:
        parts: Crossref date-parts, such as ``[[2017, 9, 8]]`` or ``[[2017]]``.

    Returns:
        ``("2017-09-08", "day")``, ``("2017-09", "month")`` or
        ``("2017", "year")``; ``(None, None)`` when there is no date.
    """
    try:
        values = [int(x) for x in (parts or [[]])[0] if x is not None]
    except (TypeError, ValueError):
        return None, None
    if not values:
        return None, None
    precision = ("year", "month", "day")[min(len(values), 3) - 1]
    return "-".join([f"{values[0]:04d}"] + [f"{v:02d}" for v in values[1:3]]), precision


def iso_date(value) -> tuple[str | None, str | None]:
    """An ISO date and its precision from the many forms sources use.

    Args:
        value: ``"2019"``, ``"2019-05"``, ``"2019-05-22T10:00:00Z"`` or v3's
            ``"22/5/2019"``.

    Returns:
        ``(date, precision)`` with precision ``year``, ``month`` or ``day``;
        ``(None, None)`` when no date is recognised.
    """
    if value is None:
        return None, None
    text = str(value).strip()
    import re

    m = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", text)
    if m:
        y, mo, d = m.groups()
        if d:
            return f"{y}-{int(mo):02d}-{int(d):02d}", "day"
        if mo:
            return f"{y}-{int(mo):02d}", "month"
        return y, "year"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)   # v3's D/M/YYYY
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}", "day"
    return None, None


def _orcid(value) -> str | None:
    """The bare ORCID iD from an ORCID URL or iD.

    Args:
        value: ``"https://orcid.org/0000-0002-1825-0097"`` or the bare iD.

    Returns:
        The bare iD, or None when `value` is empty.
    """
    return str(value).rstrip("/").split("/")[-1] if value else None


def from_crossref(message: dict) -> dict:
    """Work metadata from a Crossref record.

    The date is the first of ``issued``, ``published-print``,
    ``published-online``, ``published`` and ``created`` that is present.

    Args:
        message: The ``message`` of a Crossref ``/works/{doi}`` response.

    Returns:
        The work's metadata, with ``metadata_source`` ``crossref``.
    """
    issued, precision = None, None
    for key in ("issued", "published-print", "published-online", "published", "created"):
        issued, precision = _date((message.get(key) or {}).get("date-parts"))
        if issued:
            break
    authors = [{k: v for k, v in {"given": a.get("given"), "family": a.get("family"), "name": a.get("name"),
                                  "orcid": _orcid(a.get("ORCID"))}.items() if v}
               for a in message.get("author") or [] if isinstance(a, dict)]
    return {
        "title": (message.get("title") or [None])[0],
        "work_type": crossref_type(message.get("type")),
        "container_title": (message.get("container-title") or [None])[0],
        "publisher": message.get("publisher"),
        "issued": issued,
        "issued_precision": precision,
        "authors": authors,
        "metadata_source": "crossref",
    }


def from_datacite(attributes: dict) -> dict:
    """Work metadata from a DataCite record.

    The date is the ``Issued`` date, else the publication year.

    Args:
        attributes: The record's ``attributes``.

    Returns:
        The work's metadata, with ``metadata_source`` ``datacite``.
    """
    a = attributes or {}
    issued, precision = None, None
    for d in a.get("dates") or []:
        if isinstance(d, dict) and (d.get("dateType") or "").lower() == "issued":
            issued, precision = iso_date(d.get("date"))
            break
    if not issued and a.get("publicationYear"):
        issued, precision = str(a["publicationYear"]), "year"
    authors = []
    for c in a.get("creators") or []:
        if not isinstance(c, dict):
            continue
        orcid = next((i.get("nameIdentifier") for i in c.get("nameIdentifiers") or []
                      if isinstance(i, dict) and (i.get("nameIdentifierScheme") or "").upper() == "ORCID"), None)
        authors.append({k: v for k, v in {"given": c.get("givenName"), "family": c.get("familyName"),
                                          "name": c.get("name"), "orcid": _orcid(orcid)}.items() if v})
    publisher = a.get("publisher")
    types = a.get("types") or {}
    container = a.get("container") or {}
    return {
        "title": ((a.get("titles") or [{}])[0] or {}).get("title"),
        "work_type": datacite_type(types),
        "container_title": container.get("title") if isinstance(container, dict) else None,
        "publisher": publisher.get("name") if isinstance(publisher, dict) else publisher,
        "issued": issued,
        "issued_precision": precision,
        "authors": authors,
        "metadata_source": "datacite",
    }


def from_hint(hint: dict, source: str) -> dict:
    """Work metadata from what a source said about the work when it reported the link.

    Used when the work has no DOI, or its DOI could not be looked up.

    Args:
        hint: A raw link's ``hint``: ``title``, ``work_type``, ``publisher``,
            ``issued`` and ``authors``, any of them missing.
        source: The source that gave the hint; also the ``metadata_source``.

    Returns:
        The work's metadata.
    """
    issued, precision = iso_date(hint.get("issued"))
    return {
        "title": hint.get("title"),
        "work_type": crossref_type(hint.get("work_type"), source),
        "container_title": None,
        "publisher": hint.get("publisher"),
        "issued": issued,
        "issued_precision": precision,
        "authors": hint.get("authors") or [],
        "metadata_source": source,
    }


def from_inventory(row) -> dict:
    """Work metadata for a citing work that is itself a NERC dataset.

    Args:
        row: The dataset's ``datasets`` row.

    Returns:
        The work's metadata, with ``work_type`` ``dataset`` and
        ``metadata_source`` ``inventory``.
    """
    year = row["publication_year"]
    return {
        "title": row["title"],
        "work_type": "dataset",
        "container_title": None,
        "publisher": row["publisher"],
        "issued": str(year) if year else None,
        "issued_precision": "year" if year else None,
        "authors": json.loads(row["authors"] or "[]"),
        "metadata_source": "inventory",
    }


def fetch_doi(client, doi: str) -> dict | None:
    """Metadata for a DOI from Crossref or DataCite.

    DOIs under a known DataCite prefix (`DATACITE_PREFIXES`) are looked up
    at DataCite first; any other DOI at Crossref first.

    Args:
        client: The HTTP client.
        doi: A bare lower-case DOI.

    Returns:
        The work's metadata, or None if neither agency knows the DOI.

    Raises:
        citations.http.HttpError: If a lookup fails other than with a 404.
    """
    order = ("datacite", "crossref") if doi.startswith(DATACITE_PREFIXES) else ("crossref", "datacite")
    for agency in order:
        if agency == "crossref":
            payload = client.get_json(CROSSREF_WORK.format(doi=quote(doi, safe="/")),
                                      params={"mailto": client.mailto} if client.mailto else None)
            if payload and payload.get("message"):
                return from_crossref(payload["message"])
        else:
            payload = client.get_json(DATACITE_WORK.format(doi=quote(doi, safe="/")))
            if payload and payload.get("data"):
                return from_datacite(payload["data"].get("attributes"))
    return None


def _authors_for_citation(authors: list[dict]) -> list:
    """Authors in the form `citations.citation_text.format_citations` reads.

    Args:
        authors: ``{given, family, name, orcid}`` dicts, or None.

    Returns:
        ``[given, family]`` pairs, or a name for an author with no family name.
    """
    out = []
    for a in authors or []:
        if a.get("family"):
            out.append([a.get("given") or "", a["family"]])
        elif a.get("name"):
            out.append(a["name"])
    return out


def _previous_strings(settings) -> dict:
    """Real citation strings already published in ``Results/v3``, to reuse rather than fetch again.

    Args:
        settings: The run's settings, for the folder.

    Returns:
        ``{doi: citation}`` for every row whose ``PubCitationStr`` is a real
        citation; empty if there is no earlier file.
    """
    path = settings.v3_dir / "latest_results.csv"
    reuse = {}
    if not path.exists():
        return reuse
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            found = normalise_id(row.get("publication_doi"))
            if found and found[1] == "doi" and is_real_citation(row.get("PubCitationStr")):
                reuse.setdefault(found[0], row["PubCitationStr"])
    return reuse


def _throttled(client) -> int:
    """429 responses so far from the APIs the works stage calls.

    Args:
        client: The HTTP client.

    Returns:
        The total count of 429 responses in `WORKS_BUCKETS`.
    """
    counts = client.throttled() if hasattr(client, "throttled") else {}
    return sum(n for bucket, n in counts.items() if bucket in WORKS_BUCKETS)


def run_works(con, client, settings) -> str:
    """Run the works stage: metadata and a citation string for every citing work.

    Every citing work in a source's good run gets metadata, from the first that
    applies: the inventory (a NERC dataset), Crossref or DataCite (a DOI), or the
    best source hint (`HINT_PRIORITY`). Works fetched less than
    ``works_refresh_days`` ago are skipped. Works are saved
    `SAVE_EVERY` at a time, so a run stopped by the job's time limit keeps
    what it fetched. A failed lookup is stored without ``fetched_at``, so the
    next run tries it again.

    Each work then gets a citation string once: a formatted citation reused
    from earlier results or fetched by DOI content negotiation, else one built
    from the metadata, else the work's link.

    Args:
        con: An open store connection.
        client: The HTTP client.
        settings: The run's settings.

    Returns:
        ``"success"``; ``"partial"`` when more than 20% of the DOI lookups
        failed; or ``"failed"``.
    """
    run_id = db.start_run(con, "works")
    throttled_before = _throttled(client)
    try:
        good = {r["source"]: r["good_run_id"] for r in con.execute("SELECT * FROM source_state WHERE source<>'inventory'")}
        if not good:
            raise RuntimeError("No successful harvest to collect citing works from.")
        clause = " OR ".join("(source=? AND run_id=?)" for _ in good)
        params = [x for item in good.items() for x in item]
        hints: dict[str, dict] = {}
        kinds: dict[str, str] = {}
        for row in con.execute(f"SELECT source, citing_id, citing_id_type, hint FROM raw_links WHERE {clause}", params):
            kinds[row["citing_id"]] = row["citing_id_type"]
            if row["hint"]:
                current = hints.get(row["citing_id"])
                rank = HINT_PRIORITY.index(row["source"]) if row["source"] in HINT_PRIORITY else 99
                if current is None or rank < current[0]:
                    hints[row["citing_id"]] = (rank, row["source"], json.loads(row["hint"]))

        existing = {r["citing_id"]: r for r in con.execute("SELECT * FROM works")}
        inventory = {r["doi"]: r for r in con.execute("SELECT * FROM datasets")}
        due, rows = [], {}
        for citing_id, kind in kinds.items():
            old = existing.get(citing_id)
            age = db.age_days(old["fetched_at"]) if old is not None else None
            fresh = old is not None and old["metadata_source"] is not None \
                and age is not None and age < settings.works_refresh_days
            if fresh:
                continue
            if citing_id in inventory:
                rows[citing_id] = from_inventory(inventory[citing_id])
            elif kind == "doi":
                due.append(citing_id)
            elif citing_id in hints:
                rows[citing_id] = from_hint(hints[citing_id][2], hints[citing_id][1])
            elif old is None:
                rows[citing_id] = {"metadata_source": None}

        log.info("works: %d known, %d to fetch, %d from inventory or source hints", len(existing), len(due), len(rows))
        retry = set()   # lookups that failed: stored without fetched_at, so the next run tries again

        def save(batch: dict):
            """Insert or update a batch of works' metadata in one transaction.

            A work's existing citation string is kept.

            Args:
                batch: ``{citing_id: metadata}``.
            """
            now = db.now_iso()
            with db.transaction(con):
                for citing_id, meta in batch.items():
                    old = existing.get(citing_id)
                    con.execute(
                        "INSERT INTO works (citing_id, citing_id_type, title, work_type, container_title, publisher, "
                        "issued, issued_precision, authors, citation_text, citation_source, metadata_source, "
                        "fetched_at, citation_fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(citing_id) DO UPDATE SET title=excluded.title, work_type=excluded.work_type, "
                        "container_title=excluded.container_title, publisher=excluded.publisher, "
                        "issued=excluded.issued, issued_precision=excluded.issued_precision, authors=excluded.authors, "
                        "metadata_source=excluded.metadata_source, fetched_at=excluded.fetched_at",
                        (citing_id, kinds.get(citing_id), meta.get("title"), meta.get("work_type"),
                         meta.get("container_title"), meta.get("publisher"), meta.get("issued"),
                         meta.get("issued_precision"), json.dumps(meta.get("authors") or [], ensure_ascii=False),
                         old["citation_text"] if old else None, old["citation_source"] if old else None,
                         meta.get("metadata_source"), None if citing_id in retry else now,
                         old["citation_fetched_at"] if old else None),
                    )

        # Saved as they arrive, SAVE_EVERY at a time, so a run stopped by the job's
        # time limit keeps what it fetched and the next run carries on from there.
        save(rows)
        errors = not_found = 0
        for start in range(0, len(due), SAVE_EVERY):
            batch = {}
            for doi, meta, error in client.map(lambda d: fetch_doi(client, d), due[start:start + SAVE_EVERY]):
                if error is not None:
                    errors += 1
                    if doi in existing:
                        continue  # keep what we had; retried next run
                    retry.add(doi)  # use the source's hint for now, but don't treat it as fetched
                if meta is None:
                    not_found += error is None
                    meta = from_hint(hints[doi][2], hints[doi][1]) if doi in hints else {"metadata_source": None}
                batch[doi] = meta
            save(batch)
            rows.update(batch)
            log.info("works: %d/%d fetched (%d errors)", min(start + SAVE_EVERY, len(due)), len(due), errors)

        # Citation strings for works that have none yet (every work ends up with at least a link,
        # so this happens once), or only a fallback or link made before metadata arrived.
        def citation_due(r):
            """Whether a work needs a citation string made.

            Args:
                r: A ``works`` row.

            Returns:
                True when it has none, or has only a fallback or link made before its
                metadata was just improved.
            """
            if r["citation_text"]:
                return r["citation_source"] in ("fallback", "link") and r["citing_id"] in rows  # metadata just improved
            return True

        need = [r for r in con.execute("SELECT * FROM works") if citation_due(r)]
        reuse = _previous_strings(settings)
        reuse.update({r["citing_id"]: r["citation_text"] for r in con.execute(
            "SELECT citing_id, citation_text FROM works WHERE citation_source IN ('formatter', 'reused')")})
        limiter = client if hasattr(client, "limited") else None
        stats = Counter()
        for start in range(0, len(need), SAVE_EVERY):
            chunk = need[start:start + SAVE_EVERY]
            cite_rows = [{
                "data_doi": None,
                "pub_doi": r["citing_id"] if r["citing_id_type"] == "doi" else None,
                "pub_title": r["title"],
                "pub_authors": _authors_for_citation(json.loads(r["authors"] or "[]")),
                "publicationYear": (r["issued"] or "")[:4] or None,
                "pub_date": r["issued"],
                "pub_publisher": r["container_title"] or r["publisher"],
                "bucket": _agency_bucket(r),
            } for r in chunk]
            strings, origins, chunk_stats = format_citations(
                cite_rows, reuse=reuse, min_success_rate=settings.min_citation_success_rate,
                pause=0.05, workers=getattr(client, "workers", 1), limiter=limiter)
            stats.update(chunk_stats)
            now = db.now_iso()
            with db.transaction(con):
                for r, text, origin in zip(chunk, strings, origins):
                    if not text:
                        # Nothing to build a citation from (often a web page a data centre linked
                        # to): the link itself, rather than an empty citation.
                        text, origin = work_url(r["citing_id"], r["citing_id_type"]), "link"
                        stats["link"] += 1
                    con.execute("UPDATE works SET citation_text=?, citation_source=?, citation_fetched_at=? "
                                "WHERE citing_id=?", (text or None, origin or None, now, r["citing_id"]))
            if len(need) > SAVE_EVERY:
                log.info("works: citation strings %d/%d", min(start + SAVE_EVERY, len(need)), len(need))
        stats = dict(sorted(stats.items()))

        total = con.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        status = "success" if not due or errors / len(due) <= 0.2 else "partial"
        db.finish_run(con, run_id, status, rows=total, items=len(due), errors=errors,
                      details={"fetched": len(due), "not_found": not_found, "citations": stats,
                               "throttled_429": _throttled(client) - throttled_before})
        log.info("works: %s; %d works, citation strings %s", status, total, stats)
        return status
    except Exception as error:  # noqa: BLE001
        con.rollback()
        db.finish_run(con, run_id, "failed", message=f"{type(error).__name__}: {error}"[:1000])
        log.error("works failed: %s", error)
        return "failed"
