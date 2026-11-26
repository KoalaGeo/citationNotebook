"""Reconciliation against DataCite's own citationCount, dataset by dataset.

Every link DataCite counts is harvested (sources.datacite), so a dataset whose
harvested DataCite links fall short of its ``citationCount`` points at a failed
or incomplete harvest. Differences in what is *counted* are explained by the
links' class and status (for example DataCite counts dataset-to-dataset links,
which v4 publishes as related datasets).
"""

from __future__ import annotations

from collections import defaultdict

from . import db


def reconcile(con) -> tuple[list[dict], dict]:
    """Compare the harvest with DataCite's ``citationCount``, dataset by dataset.

    Only datasets that DataCite counts as cited, or that have a counted link
    here, are compared.

    Args:
        con: An open store connection, after the merge stage.

    Returns:
        ``(rows, summary)``. Each row is one dataset, with the columns of
        ``Results/v4/reconciliation.csv``; rows are sorted with the most missing
        links first. The summary holds ``datacite_cited_datasets``,
        ``datacite_citations``, ``datacite_links_harvested``,
        ``incomplete_datasets``, ``incomplete_share`` (which the publishing guard
        checks), ``pipeline_counted_citations`` and ``pipeline_cited_datasets``.
    """
    datasets = {r["doi"]: r for r in con.execute("SELECT * FROM datasets")}
    good = db.good_run(con, "datacite")
    harvested = defaultdict(set)
    if good is not None:
        for row in con.execute(
            "SELECT data_doi, citing_id FROM raw_links WHERE source='datacite' AND run_id=? "
            "AND source_relation LIKE 'citations%'", (good["good_run_id"],)
        ):
            harvested[row["data_doi"]].add(row["citing_id"])
    links = defaultdict(list)
    for row in con.execute("SELECT data_doi, citing_id, relation_class, counted, status FROM links"):
        links[row["data_doi"]].append(row)

    rows = []
    for doi, ds in datasets.items():
        count = ds["datacite_citation_count"] or 0
        mine = links.get(doi, [])
        counted = sum(r["counted"] for r in mine)
        if count == 0 and counted == 0:
            continue
        dc_ids = harvested.get(doi, set())
        dc_rows = [r for r in mine if r["citing_id"] in dc_ids]
        rows.append({
            "doi": doi,
            "data_centre": ds["data_centre"],
            "datacite_citation_count": count,
            "datacite_links_harvested": len(dc_ids),
            "missing_vs_datacite": max(count - len(dc_ids), 0),
            "datacite_links_counted": sum(r["counted"] for r in dc_rows),
            "datacite_links_dataset_link": sum(r["relation_class"] == "dataset-link" for r in dc_rows),
            "datacite_links_excluded": sum(r["status"] == "excluded" for r in dc_rows),
            "datacite_links_other_class": sum(r["status"] == "included" and not r["counted"]
                                              and r["relation_class"] != "dataset-link" for r in dc_rows),
            "pipeline_counted": counted,
            "pipeline_counted_not_in_datacite": sum(r["counted"] and r["citing_id"] not in dc_ids for r in mine),
            "pipeline_all_links": len(mine),
            "complete": len(dc_ids) >= count,
        })
    rows.sort(key=lambda r: (-r["missing_vs_datacite"], r["doi"]))
    cited = [r for r in rows if r["datacite_citation_count"] > 0]
    incomplete = [r for r in cited if not r["complete"]]
    summary = {
        "datacite_cited_datasets": len(cited),
        "datacite_citations": sum(r["datacite_citation_count"] for r in cited),
        "datacite_links_harvested": sum(r["datacite_links_harvested"] for r in cited),
        "incomplete_datasets": len(incomplete),
        "incomplete_share": round(len(incomplete) / len(cited), 4) if cited else 0.0,
        "pipeline_counted_citations": sum(r["pipeline_counted"] for r in rows),
        "pipeline_cited_datasets": sum(r["pipeline_counted"] > 0 for r in rows),
    }
    return rows, summary
