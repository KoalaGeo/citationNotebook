"""Write Results/v4 (datasets, links, works, reconciliation, manifest) and the v3-compatible copy.

v4 rules: bare lower-case DOIs; ISO 8601 dates; empty means null (no
"Info not given"); lists and objects are JSON (a JSON string inside CSV); JSON
files are flat arrays carrying data_centre, not grouped by data centre.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from . import db, guards
from .config import CENTRE_NAMES, CODE_VERSION, UNKNOWN_CENTRE_NAME
from .reconcile import reconcile
from .relations import to_kebab

log = logging.getLogger(__name__)

DATASET_COLUMNS = ["doi", "data_centre", "data_centre_name", "publisher", "title", "publication_year",
                   "resource_type_general", "registered", "authors", "counted_citations", "related_links",
                   "excluded_links", "datacite_citation_count", "first_cited"]
LINK_COLUMNS = ["link_id", "data_doi", "data_centre", "citing_id", "citing_id_type", "relation_type", "relation_class",
                "counted", "status", "exclusion_reason", "sources", "source_relations", "first_seen", "last_seen"]
WORK_COLUMNS = ["citing_id", "citing_id_type", "title", "work_type", "container_title", "publisher", "issued",
                "issued_precision", "authors", "citation_text", "metadata_source", "fetched_at"]
RECONCILIATION_COLUMNS = ["doi", "data_centre", "datacite_citation_count", "datacite_links_harvested",
                          "missing_vs_datacite", "datacite_links_counted", "datacite_links_dataset_link",
                          "datacite_links_excluded", "datacite_links_other_class", "pipeline_counted",
                          "pipeline_counted_not_in_datacite", "pipeline_all_links", "complete"]
V3_COLUMNS = ["data_doi", "data_publisher", "data_title", "data_publication_year", "data_authors", "relation_type_id",
              "publication_doi", "publication_title", "publication_date", "publication_authors",
              "citation_event_source", "pub_publisher", "publication_type", "publicationYear", "PubCitationStr",
              "data_doi_url", "publication_doi_url", "date_added"]
V3_FILTERED_COLUMNS = ["data_doi", "data_publisher", "data_title", "data_publication_year", "data_authors",
                       "relation_type", "pub_doi", "pub_title", "pub_date", "pub_authors", "source_id",
                       "pub_publisher", "pub_type", "publicationYear"]
# The EDS citation API reads Results/v3, so its files keep the v3 pipeline's types: a float
# data_publication_year, and its placeholder text where a value is missing (never empty or null).
V3_NO_TITLE = "No title given"
V3_MISSING = "Info not given"
LEGACY_SOURCE = {"datacite": "datacite", "scholexplorer": "scholex", "overton": "overton", "crossref": "crossref"}


class PublishBlocked(RuntimeError):
    pass


# -- writing ------------------------------------------------------------------
def _atomic(path: Path, write, encoding: str = "utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            write(handle)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=isinstance(value, dict))
    return value


def write_csv(path: Path, columns: list[str], rows: list[dict], cell=_cell, encoding: str = "utf-8"):
    def write(handle):
        writer = csv.writer(handle, lineterminator="\n")   # LF, as v3 wrote it; nothing for git to normalise
        writer.writerow(columns)
        for row in rows:
            writer.writerow([cell(row.get(c)) for c in columns])
    _atomic(path, write, encoding)


def write_json(path: Path, data, lines: bool = False, compact: bool = False):
    def write(handle):
        if lines:
            for record in data:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        elif compact:
            json.dump(data, handle, ensure_ascii=False)   # one line, no trailing newline, as v3 wrote it
        else:
            json.dump(data, handle, ensure_ascii=False, indent=None if isinstance(data, list) else 2)
            handle.write("\n")
    _atomic(path, write)


V4_FILES = ("datasets.csv", "datasets.json", "links.csv", "links.jsonl", "works.csv", "works.json",
            "reconciliation.csv")


def file_hashes(folder: Path, names=V4_FILES) -> dict:
    """sha256 and size of each published file, recorded in the manifest.

    The files are fetched one by one (raw.githubusercontent.com caches each for a
    few minutes), so a reader can be handed a new manifest with an old links.csv.
    Checking the hashes tells it the set is consistent before it uses it.
    """
    out = {}
    for name in names:
        data = (folder / name).read_bytes()
        out[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    return out


# -- building rows ------------------------------------------------------------
def _authors_names(authors: list[dict]) -> list[str]:
    out = []
    for a in authors or []:
        if a.get("name"):
            out.append(a["name"])
        elif a.get("family"):
            out.append(", ".join(x for x in (a.get("family"), a.get("given")) if x))
    return out


def build(con) -> dict:
    datasets = [dict(r) for r in con.execute("SELECT * FROM datasets ORDER BY doi")]
    links = [dict(r) for r in con.execute("SELECT * FROM links ORDER BY data_doi, citing_id")]
    used = {l["citing_id"] for l in links}
    works = [dict(r) for r in con.execute("SELECT * FROM works ORDER BY citing_id") if r["citing_id"] in used]
    work_by_id = {w["citing_id"]: w for w in works}

    for link in links:
        link["counted"] = bool(link["counted"])
        link["sources"] = json.loads(link["sources"])
        link["source_relations"] = json.loads(link["source_relations"])
    for work in works:
        work["authors"] = json.loads(work["authors"] or "[]")

    per = defaultdict(lambda: {"counted": 0, "related": 0, "excluded": 0, "first": None})
    for link in links:
        stats = per[link["data_doi"]]
        if link["status"] == "excluded":
            stats["excluded"] += 1
        elif link["counted"]:
            stats["counted"] += 1
            issued = (work_by_id.get(link["citing_id"]) or {}).get("issued")
            if issued and (stats["first"] is None or issued < stats["first"]):
                stats["first"] = issued
        else:
            stats["related"] += 1
    for ds in datasets:
        stats = per.get(ds["doi"], {"counted": 0, "related": 0, "excluded": 0, "first": None})
        ds["authors"] = json.loads(ds["authors"] or "[]")
        ds["data_centre_name"] = CENTRE_NAMES.get(ds["data_centre"]) if ds["data_centre"] else None
        ds["counted_citations"] = stats["counted"]
        ds["related_links"] = stats["related"]
        ds["excluded_links"] = stats["excluded"]
        ds["first_cited"] = stats["first"]
        ds.pop("run_id", None)
    return {"datasets": datasets, "links": links, "works": works}


def v3_rows(data: dict) -> tuple[list[dict], list[dict]]:
    datasets = {d["doi"]: d for d in data["datasets"]}
    works = {w["citing_id"]: w for w in data["works"]}
    kept, filtered = [], []
    for link in data["links"]:
        ds, work = datasets[link["data_doi"]], works.get(link["citing_id"], {})
        legacy = sorted({LEGACY_SOURCE.get(s.split(":")[0], s) for s in link["sources"]})
        source = next((s for s in ("datacite", "scholex", "overton", "crossref") if s in legacy), legacy[0])
        pub_authors = _authors_names(work.get("authors"))
        publisher = ds["data_centre_name"] or ds["publisher"] or UNKNOWN_CENTRE_NAME
        issued = work.get("issued")
        year = ds["publication_year"]
        base = {
            "data_doi": ds["doi"],
            "data_publisher": publisher,
            "data_title": ds["title"] or V3_NO_TITLE,
            "data_publication_year": float(year) if year is not None else None,
            "data_authors": _authors_names(ds["authors"]),
        }
        title = work.get("title") or V3_MISSING
        container = work.get("container_title") or work.get("publisher") or V3_MISSING
        work_type = work.get("work_type") or V3_MISSING
        if link["counted"]:
            kept.append({
                **base,
                "relation_type_id": to_kebab(link["relation_type"]),
                "publication_doi": link["citing_id"],
                "publication_title": title,
                "publication_date": issued,
                "publication_authors": pub_authors,
                "citation_event_source": source,
                "pub_publisher": container,
                "publication_type": work_type,
                "publicationYear": issued[:4] if issued else None,
                "PubCitationStr": work.get("citation_text"),
                "data_doi_url": f"doi.org/{ds['doi']}",
                "publication_doi_url": f"doi.org/{link['citing_id']}" if link["citing_id_type"] == "doi" else link["citing_id"],
                "date_added": link["first_seen"],
            })
        elif link["status"] == "excluded":
            filtered.append({
                **base,
                "relation_type": to_kebab(link["relation_type"]),
                "pub_doi": link["citing_id"],
                "pub_title": title,
                "pub_date": issued,
                "pub_authors": pub_authors,
                "source_id": source,
                "pub_publisher": container,
                "pub_type": work_type,
                "publicationYear": issued[:4] if issued else None,
            })
    return kept, filtered


def _v3_cell(value):
    # v3 consumers read list columns as Python list literals, as pandas wrote them.
    if isinstance(value, list):
        return repr(value)
    return "" if value is None else value


def write_v3(settings, data: dict):
    kept, filtered = v3_rows(data)
    # Encodings as v3 wrote them: latest_results.csv with a BOM (so Excel opens it correctly),
    # filtered_out_df.csv without. The JSON on one line.
    write_csv(settings.v3_dir / "latest_results.csv", V3_COLUMNS, kept, cell=_v3_cell, encoding="utf-8-sig")
    write_csv(settings.v3_dir / "filtered_out_df.csv", V3_FILTERED_COLUMNS, filtered, cell=_v3_cell, encoding="utf-8")
    grouped = defaultdict(list)
    for row in kept:
        grouped[row["data_publisher"]].append({k: v for k, v in row.items() if k != "data_publisher"})
    write_json(settings.v3_dir / "latest_results.json", dict(sorted(grouped.items())), compact=True)
    return len(kept), len(filtered)


# -- the stage ------------------------------------------------------------------
def _previous_manifest(settings) -> dict | None:
    path = settings.v4_dir / "manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def counts(data: dict, con) -> dict:
    links = data["links"]
    return {
        "datasets": len(data["datasets"]),
        "datasets_by_centre": dict(sorted(Counter(d["data_centre"] or "unknown" for d in data["datasets"]).items())),
        "datasets_cited": sum(d["counted_citations"] > 0 for d in data["datasets"]),
        "links": len(links),
        "counted_links": sum(l["counted"] for l in links),
        "links_by_class": dict(sorted(Counter(l["relation_class"] for l in links).items())),
        "links_by_status": dict(sorted(Counter(l["status"] for l in links).items())),
        "exclusions": dict(sorted(Counter(l["exclusion_reason"] for l in links if l["exclusion_reason"]).items())),
        "links_by_source": guards.links_by_source(con),
        "works": len(data["works"]),
    }


def run_publish(con, settings, force: bool = False) -> str:
    run_id = db.start_run(con, "publish")
    try:
        rec_rows, rec_summary = reconcile(con)
        problems, warnings, report = guards.check(con, settings, _previous_manifest(settings), rec_summary)
        for warning in warnings:
            log.warning("publish: %s", warning)
        if problems and not force:
            for problem in problems:
                log.error("publish blocked: %s", problem)
            db.finish_run(con, run_id, "blocked", message=" | ".join(problems)[:2000],
                          details={"problems": problems, "warnings": warnings})
            return "blocked"

        data = build(con)
        v4 = settings.v4_dir
        write_csv(v4 / "datasets.csv", DATASET_COLUMNS, data["datasets"])
        write_json(v4 / "datasets.json", [{c: d.get(c) for c in DATASET_COLUMNS} for d in data["datasets"]])
        write_csv(v4 / "links.csv", LINK_COLUMNS, data["links"])
        write_json(v4 / "links.jsonl", [{c: l.get(c) for c in LINK_COLUMNS} for l in data["links"]], lines=True)
        write_csv(v4 / "works.csv", WORK_COLUMNS, data["works"])
        write_json(v4 / "works.json", [{c: w.get(c) for c in WORK_COLUMNS} for w in data["works"]])
        write_csv(v4 / "reconciliation.csv", RECONCILIATION_COLUMNS, rec_rows)
        v3_counts = write_v3(settings, data) if settings.write_v3 else None

        manifest = {
            "schema": "nerc-eds-citations/v4",
            "generated_at": db.now_iso(),
            "code_version": CODE_VERSION,
            "git_commit": os.environ.get("GITHUB_SHA"),
            "client_id": settings.client_id,
            "settings": {
                "predates_tolerance_years": settings.predates_tolerance_years,
                "max_source_age_days": settings.max_source_age_days,
                "max_row_drop": settings.max_row_drop,
                "reconcile_threshold": settings.reconcile_threshold,
            },
            "sources": report,
            "counts": counts(data, con),
            "reconciliation": rec_summary,
            "guards": {"problems": problems, "warnings": warnings, "forced": bool(problems and force)},
            "v3_compat": {"latest_results_rows": v3_counts[0], "filtered_out_rows": v3_counts[1]} if v3_counts else None,
            "files": file_hashes(v4),
        }
        write_json(v4 / "manifest.json", manifest)
        db.finish_run(con, run_id, "success", rows=len(data["links"]),
                      details={"warnings": warnings, "forced_over": problems if force else []})
        log.info("publish: %d datasets, %d links (%d counted), %d works written to %s",
                 len(data["datasets"]), len(data["links"]), manifest["counts"]["counted_links"], len(data["works"]), v4)
        return "success"
    except Exception as error:  # noqa: BLE001
        db.finish_run(con, run_id, "failed", message=f"{type(error).__name__}: {error}"[:1000])
        log.error("publish failed: %s", error)
        raise