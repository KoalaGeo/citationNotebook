"""Merge: one link per (dataset, citing work) from every source's latest good harvest.

Identifiers were normalised at harvest (lower-case DOIs, canonical URLs), so the
same work from two sources is one link. Every source that found a link is kept
in ``sources``; the most specific relation wins (a citation from DataCite beats
a similarity link from Scholexplorer for the same pair).
"""

from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from datetime import date

from . import db
from .filters import exclusion_reason
from .ids import is_nerc_dataset, link_id, normalise_id
from .relations import COUNTED_CLASSES, PRIORITY, USE_CLASSES, relation_class

log = logging.getLogger(__name__)


def source_label(source: str, provenance: str) -> str:
    """The label a raw link's source gets in a link's ``sources``.

    Args:
        source: The harvest source.
        provenance: The raw link's finer origin within the source.

    Returns:
        ``datacite`` or ``datacite:<provenance>`` (for example
        ``datacite:crossref``), ``crossref:datacitations``, or the source name.
    """
    if source == "datacite":
        return f"datacite:{provenance}" if provenance not in ("datacite", "") else "datacite"
    if source == "crossref":
        return "crossref:datacitations"
    return source


def _seed_history(con, settings) -> int:
    """First-seen dates for a fresh store, from earlier published results.

    Reads ``Results/v4/links.csv`` if it exists, else the ``date_added`` column
    of ``Results/v3/latest_results.csv``, so links keep the date they were first
    found when the store is rebuilt.

    Args:
        con: An open store connection.
        settings: The run's settings, for the results folders.

    Returns:
        How many links were seeded into ``link_history``.
    """
    seeded = {}
    v4 = settings.v4_dir / "links.csv"
    v3 = settings.v3_dir / "latest_results.csv"
    if v4.exists():
        with open(v4, encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                seeded[row["link_id"]] = (row["data_doi"], row["citing_id"], row["first_seen"], row["last_seen"])
    elif v3.exists():
        with open(v3, encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                data_doi = (row.get("data_doi") or "").strip().lower()
                found = normalise_id(row.get("publication_doi"), exclude=data_doi)
                added = (row.get("date_added") or "").strip()
                if not data_doi or not found or not added:
                    continue
                key = link_id(data_doi, found[0])
                if key not in seeded or added < seeded[key][2]:
                    seeded[key] = (data_doi, found[0], added, added)
    con.executemany(
        "INSERT OR IGNORE INTO link_history (link_id, data_doi, citing_id, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
        [(k, *v) for k, v in seeded.items()],
    )
    return len(seeded)


def run_merge(con, settings, today: str | None = None) -> str:
    """Run the merge stage: one classified link per dataset and citing work.

    Takes every raw link from each source's good run, drops those whose dataset
    is no longer in the inventory, and groups the rest by ``(data_doi,
    citing_id)``. For each pair the highest-priority relation wins
    (`citations.relations.PRIORITY`); a link to another NERC dataset is
    classed ``dataset-link``; the exclusion rules are applied; and ``counted``
    is set for included ``citation`` and ``supplement`` links. ``first_seen``
    comes from ``link_history``. The ``links`` table is replaced in one
    transaction.

    Args:
        con: An open store connection.
        settings: The run's settings.
        today: The date recorded as ``last_seen`` (and ``first_seen`` for new
            links), ``YYYY-MM-DD``; today when None.

    Returns:
        ``"success"`` or ``"failed"``.
    """
    run_id = db.start_run(con, "merge")
    today = today or date.today().isoformat()
    try:
        datasets = {r["doi"]: r for r in con.execute("SELECT * FROM datasets")}
        if not datasets:
            raise RuntimeError("The inventory is empty.")
        good = {r["source"]: r["good_run_id"] for r in con.execute("SELECT * FROM source_state WHERE source<>'inventory'")}
        if not good:
            raise RuntimeError("No source has a successful harvest.")
        works = {r["citing_id"]: dict(r) for r in con.execute("SELECT * FROM works")}

        if con.execute("SELECT COUNT(*) FROM link_history").fetchone()[0] == 0:
            seeded = _seed_history(con, settings)
            log.info("merge: seeded first-seen dates for %d links from earlier results", seeded)
        history = {r["link_id"]: r for r in con.execute("SELECT * FROM link_history")}

        groups = defaultdict(list)
        orphans = 0
        clause = " OR ".join("(source=? AND run_id=?)" for _ in good)
        params = [x for item in good.items() for x in item]
        for row in con.execute(f"SELECT * FROM raw_links WHERE {clause}", params):
            if row["data_doi"] not in datasets:
                orphans += 1
                continue
            groups[(row["data_doi"], row["citing_id"])].append(row)

        out = []
        for (data_doi, citing_id), rows in groups.items():
            candidates = sorted(
                ((PRIORITY.get(relation_class(r["relation_type"]) or "", 0), r["relation_type"]) for r in rows),
                key=lambda c: (-c[0], c[1]),
            )
            relation = candidates[0][1]
            klass = relation_class(relation)
            if klass is None:
                continue
            if klass in USE_CLASSES and is_nerc_dataset(citing_id):
                klass = "dataset-link"
            sources, source_relations = set(), defaultdict(set)
            for r in rows:
                label = source_label(r["source"], r["provenance"])
                sources.add(label)
                source_relations[label].add(r["source_relation"])
            dataset = datasets[data_doi]
            reason = exclusion_reason(data_doi, citing_id, klass, works.get(citing_id), dataset["publication_year"],
                                      settings.predates_tolerance_years)
            status = "excluded" if reason else "included"
            key = link_id(data_doi, citing_id)
            first_seen = history[key]["first_seen"] if key in history else today
            out.append({
                "link_id": key,
                "data_doi": data_doi,
                "data_centre": dataset["data_centre"],
                "citing_id": citing_id,
                "citing_id_type": rows[0]["citing_id_type"],
                "relation_type": relation,
                "relation_class": klass,
                "counted": int(status == "included" and klass in COUNTED_CLASSES),
                "status": status,
                "exclusion_reason": reason,
                "sources": json.dumps(sorted(sources)),
                "source_relations": json.dumps({k: sorted(v) for k, v in sorted(source_relations.items())}),
                "first_seen": first_seen,
                "last_seen": today,
            })

        with db.transaction(con):
            con.execute("DELETE FROM links")
            con.executemany(
                "INSERT INTO links VALUES (:link_id, :data_doi, :data_centre, :citing_id, :citing_id_type, :relation_type, "
                ":relation_class, :counted, :status, :exclusion_reason, :sources, :source_relations, :first_seen, :last_seen)",
                out,
            )
            con.executemany(
                "INSERT INTO link_history (link_id, data_doi, citing_id, first_seen, last_seen) VALUES "
                "(:link_id, :data_doi, :citing_id, :first_seen, :last_seen) "
                "ON CONFLICT(link_id) DO UPDATE SET last_seen=excluded.last_seen",
                out,
            )
        by_class = defaultdict(int)
        for row in out:
            by_class[f"{row['relation_class']}:{row['status']}"] += 1
        db.finish_run(con, run_id, "success", rows=len(out), items=sum(len(v) for v in groups.values()), errors=0,
                      details={"orphaned_raw_links": orphans, "sources": sorted(good), "by_class": dict(sorted(by_class.items()))})
        log.info("merge: %d links (%d counted); %d raw links for DOIs no longer in the inventory",
                 len(out), sum(r["counted"] for r in out), orphans)
        return "success"
    except Exception as error:  # noqa: BLE001
        con.rollback()
        db.finish_run(con, run_id, "failed", message=f"{type(error).__name__}: {error}"[:1000])
        log.error("merge failed: %s", error)
        return "failed"
