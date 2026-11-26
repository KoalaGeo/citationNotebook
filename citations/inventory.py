"""The inventory: every DOI registered to the DataCite client, checked against DataCite's own total.

The inventory is the list of datasets every other stage works from. It is
only replaced when the number of unique DOIs downloaded equals the total
DataCite reports, so a truncated download never shrinks it.
"""

from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path

from . import db
from .config import data_centre

log = logging.getLogger(__name__)

DATACITE_DOIS = "https://api.datacite.org/dois"


class InventoryIncomplete(RuntimeError):
    """Fewer unique DOIs were downloaded than DataCite reports for the client.

    The inventory run fails and the previous inventory stays in use.
    """


def _orcid(creator: dict) -> str | None:
    """The ORCID iD of a DataCite creator.

    Args:
        creator: One entry of a record's ``creators``.

    Returns:
        The bare iD (``0000-0002-1825-0097``), or None if the creator has none.
    """
    for ident in creator.get("nameIdentifiers") or []:
        if not isinstance(ident, dict):
            continue
        if (ident.get("nameIdentifierScheme") or "").upper() == "ORCID" and ident.get("nameIdentifier"):
            return ident["nameIdentifier"].rstrip("/").split("/")[-1]
    return None


def parse_authors(creators) -> list[dict]:
    """The authors of a DataCite record, in the form the store keeps them.

    Args:
        creators: The record's ``creators`` list, or None.

    Returns:
        A list of ``{name, given, family, orcid}`` dicts, with empty keys left
        out.
    """
    out = []
    for c in creators or []:
        if not isinstance(c, dict):
            continue
        out.append({k: v for k, v in {
            "name": c.get("name"),
            "given": c.get("givenName"),
            "family": c.get("familyName"),
            "orcid": _orcid(c),
        }.items() if v})
    return out


def parse_record(record: dict) -> tuple[dict, list[dict]]:
    """A dataset row and its related identifiers from one DataCite record.

    Args:
        record: One item of the DataCite REST API's ``data`` array (JSON:API).

    Returns:
        ``(row, relations)``: the ``datasets`` row, and a list of
        ``dataset_relations`` rows (relation type, related identifier and its
        type). The DOI is lower case; it is empty when the record has none.
    """
    a = record.get("attributes") or {}
    doi = (a.get("doi") or record.get("id") or "").strip().lower()
    publisher = a.get("publisher")
    publisher_name = publisher.get("name") if isinstance(publisher, dict) else publisher
    titles = a.get("titles") or []
    year = a.get("publicationYear")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    row = {
        "doi": doi,
        "data_centre": data_centre(publisher_name),
        "publisher": publisher_name,
        "title": (titles[0] or {}).get("title") if titles else None,
        "publication_year": year,
        "resource_type_general": (a.get("types") or {}).get("resourceTypeGeneral"),
        "registered": a.get("registered"),
        "authors": json.dumps(parse_authors(a.get("creators")), ensure_ascii=False),
        "datacite_citation_count": int(a.get("citationCount") or 0),
    }
    relations = [
        {
            "doi": doi,
            "relation_type": r.get("relationType"),
            "related_raw": r.get("relatedIdentifier"),
            "related_type": r.get("relatedIdentifierType"),
        }
        for r in a.get("relatedIdentifiers") or []
        if isinstance(r, dict) and r.get("relatedIdentifier")
    ]
    return row, relations


def fetch_records(client, client_id: str) -> tuple[list[dict], int | None]:
    """Every DataCite record of a client, by cursor paging.

    Cursor paging has no 10,000-record limit and skips no pages.

    Args:
        client: The HTTP client.
        client_id: The DataCite client, for example ``bl.nerc``.

    Returns:
        ``(records, total)``: every record, and the total DataCite reported on
        the first page (None if it gave none).

    Raises:
        citations.http.HttpError: If a page cannot be fetched.
    """
    extra = {"affiliation": "true", "publisher": "true"}
    params = {"client-id": client_id, "page[size]": 1000, "page[cursor]": 1, **extra}
    url, records, total = DATACITE_DOIS, [], None
    for _ in range(1000):
        page = client.get_json(url, params=params, allow_404=False)
        if total is None:
            total = (page.get("meta") or {}).get("total")
        data = page.get("data") or []
        records.extend(data)
        log.info("inventory: %d / %s records", len(records), total)
        url = (page.get("links") or {}).get("next")
        if not url or not data:
            break
        # The cursor link does not always repeat these switches.
        params = {k: v for k, v in extra.items() if f"{k}=" not in url} or None
    return records, total


def load_snapshot(path: Path) -> list[dict]:
    """Read DataCite records saved by `save_snapshot` (or a raw API response).

    Args:
        path: A ``.json`` or ``.json.gz`` file holding a list of records or an
            object with a ``data`` list.

    Returns:
        The records.
    """
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    return data["data"] if isinstance(data, dict) else data


def save_snapshot(records: list[dict], path: Path):
    """Save downloaded DataCite records, so a later inventory can be run from them offline.

    Args:
        records: The records, as `fetch_records` returns them.
        path: The ``.json.gz`` file to write; its folder is created if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(records, handle)


def run_inventory(con, client, client_id: str, snapshot: Path | None = None, save_to: Path | None = None) -> str:
    """Run the inventory stage.

    Downloads every record of the client (or reads a snapshot), parses them,
    and replaces the ``datasets`` and ``dataset_relations`` tables in one
    transaction, but only if the number of unique DOIs equals DataCite's total.

    Args:
        con: An open store connection.
        client: The HTTP client.
        client_id: The DataCite client.
        snapshot: Read the records from this file instead of the API.
        save_to: Also save the downloaded records to this file.

    Returns:
        ``"success"`` or ``"failed"``. On failure the previous inventory stays
        in use.
    """
    run_id = db.start_run(con, "inventory")
    try:
        if snapshot:
            records = load_snapshot(Path(snapshot))
            total = len({(r.get("attributes") or {}).get("doi", r.get("id", "")).lower() for r in records})
            log.info("inventory: %d records from snapshot %s", len(records), snapshot)
        else:
            records, total = fetch_records(client, client_id)
        if save_to:
            save_snapshot(records, Path(save_to))

        datasets, relations, duplicates = {}, [], 0
        for record in records:
            row, rels = parse_record(record)
            if not row["doi"]:
                continue
            if row["doi"] in datasets:
                duplicates += 1
                continue
            datasets[row["doi"]] = row
            relations.extend(rels)
        if total is not None and len(datasets) != total:
            raise InventoryIncomplete(
                f"{len(datasets)} unique DOIs retrieved but DataCite reports {total}; not replacing the inventory.")

        with db.transaction(con):
            con.execute("DELETE FROM datasets_new")
            con.execute("DELETE FROM dataset_relations_new")
            con.executemany(
                "INSERT INTO datasets_new (doi, data_centre, publisher, title, publication_year, resource_type_general, "
                "registered, authors, datacite_citation_count, run_id) VALUES "
                "(:doi, :data_centre, :publisher, :title, :publication_year, :resource_type_general, :registered, "
                ":authors, :datacite_citation_count, " + str(run_id) + ")",
                list(datasets.values()),
            )
            con.executemany(
                "INSERT INTO dataset_relations_new (doi, relation_type, related_raw, related_type, run_id) VALUES "
                "(:doi, :relation_type, :related_raw, :related_type, " + str(run_id) + ")",
                relations,
            )
            con.execute("DELETE FROM datasets")
            con.execute("INSERT INTO datasets SELECT * FROM datasets_new")
            con.execute("DELETE FROM dataset_relations")
            con.execute("INSERT INTO dataset_relations SELECT * FROM dataset_relations_new")
            con.execute("DELETE FROM datasets_new")
            con.execute("DELETE FROM dataset_relations_new")
            db.set_good_run(con, "inventory", run_id, len(datasets))
        by_centre = {}
        for row in datasets.values():
            by_centre[row["data_centre"] or "unknown"] = by_centre.get(row["data_centre"] or "unknown", 0) + 1
        db.finish_run(con, run_id, "success", rows=len(datasets), items=len(records), errors=0,
                      details={"duplicates_dropped": duplicates, "datacite_total": total, "by_centre": by_centre,
                               "related_identifiers": len(relations), "snapshot": str(snapshot) if snapshot else None})
        log.info("inventory: %d datasets (%d duplicate records dropped)", len(datasets), duplicates)
        return "success"
    except Exception as error:  # noqa: BLE001
        con.rollback()
        db.finish_run(con, run_id, "failed", message=f"{type(error).__name__}: {error}"[:1000])
        log.error("inventory failed: %s", error)
        return "failed"
