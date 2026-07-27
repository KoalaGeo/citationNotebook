"""One entry point, deterministic order, one process:

    python -m citations dois            # refresh the NERC dataset list
    python -m citations fetch           # all sources (or --source scholix ...)
    python -m citations enrich          # doi.org metadata for new publications
    python -m citations export          # filters + citation strings + Results/v3
    python -m citations all             # the whole weekly run

Replaces five separately-scheduled notebook workflows whose only coordination
was hoping the earlier crons had finished and committed.
"""

import argparse
import json
import os
import sys

from . import export as export_mod
from . import merge, store
from .http import make_session, parallel_map
from .normalize import strip_doi_url
from .sources import datacite, doiorg, overton, scholix


def _dois(conn, session, args):
    records, errors = datacite.fetch_datasets(session, limit=args.limit)
    if not records:
        sys.exit("[dois] DataCite returned no datasets; aborting rather than "
                 "wiping the dataset table.")
    store.upsert_datasets(conn, records)
    store.log(conn, "datacite/dois", "dataset list refresh", len(records), errors)
    # Keep the old intermediate for continuity / debugging.
    os.makedirs("Results/intermediate_data", exist_ok=True)
    with open("Results/intermediate_data/nerc_datacite_dois.json", "w",
              encoding="utf-8") as fh:
        json.dump([{"data_publisher": r["publisher"], "data_doi": r["data_doi"],
                    "data_title": r["title"],
                    "data_publication_year": r["publication_year"],
                    "data_authors": r["authors"]} for r in records],
                  fh, ensure_ascii=False, indent=4)
    print(f"[dois] {len(records)} datasets ({errors} errors)")


def _fetch(conn, session, args):
    dois = store.dataset_dois(conn)
    if args.limit:
        dois = dois[:args.limit]
    if not dois:
        sys.exit("[fetch] no datasets in the store; run `dois` first.")

    sources = args.source or ["datacite", "scholix", "overton"]

    if "datacite" in sources:
        rows, errors = datacite.fetch_events(session)
        store.clear_source(conn, "datacite")
        store.upsert_citations(conn, "datacite", rows)
        store.log(conn, "datacite/events", "citation events", len(rows), errors)
        print(f"[fetch/datacite] {len(rows)} events ({errors} errors)")

    if "scholix" in sources:
        rows, errors = scholix.fetch_citations(session, dois, workers=args.workers)
        store.clear_source(conn, "scholex")
        store.upsert_citations(conn, "scholex", rows)
        store.log(conn, "scholix", "inbound links", len(rows), errors)
        print(f"[fetch/scholix] {len(rows)} links ({errors} errors)")

    if "overton" in sources:
        rows, errors = overton.fetch_citations(session, dois)
        store.clear_source(conn, "overton")
        store.upsert_citations(conn, "overton", rows)
        store.log(conn, "overton", "policy documents", len(rows), errors)
        print(f"[fetch/overton] {len(rows)} documents ({errors} errors)")


def _enrich(conn, session, args):
    """doi.org metadata for every publication DOI we have not resolved yet.

    One cached lookup per DOI serves both the DataCite metadata fill and the
    Scholix type check (previously two separate multi-hour passes).
    """
    pub_dois = sorted({strip_doi_url(r["pub_doi"]) for r in store.load_citations(conn)
                       if isinstance(r["pub_doi"], str) and
                       strip_doi_url(r["pub_doi"]).startswith("10.")})
    todo = store.missing_pub_info(conn, pub_dois)
    if args.limit:
        todo = todo[:args.limit]
    print(f"[enrich] {len(pub_dois)} publication DOIs, {len(todo)} not yet cached")
    infos = parallel_map(lambda d: (d, doiorg.fetch_pub_info(session, d)),
                         todo, workers=args.workers)
    for pub_doi, info in infos:
        store.put_pub_info(conn, pub_doi, info)
    conn.commit()
    store.log(conn, "doi.org", "pub info", len(todo))


def _export(conn, session, args):
    datasets = store.load_datasets(conn)
    rows = store.load_citations(conn)
    pub_info = {strip_doi_url(r["pub_doi"]):
                store.get_pub_info(conn, strip_doi_url(r["pub_doi"])) or {}
                for r in rows if isinstance(r["pub_doi"], str)}
    df = merge.build_frame(rows, datasets, pub_info)
    if df.empty:
        sys.exit("[export] no citations in the store; run `fetch` first.")

    kept, filtered_out = merge.filter_citations(df)
    print(f"[export] {len(df)} merged rows -> {len(kept)} kept, "
          f"{len(filtered_out)} filtered out")

    # Citation strings for kept rows only; the per-DOI cache means weekly runs
    # fetch just the new publications (previously ~2h re-fetching everything).
    dois_needed = [d for d in kept["pub_doi"].unique()
                   if isinstance(d, str) and d.startswith("10.")]
    todo = store.missing_citation_strings(conn, dois_needed)
    if args.no_fetch:
        print(f"[export] --no-fetch: {len(todo)} citation strings missing from cache")
    else:
        print(f"[export] fetching {len(todo)} new citation strings "
              f"({len(dois_needed) - len(todo)} cached)")
        fetched = parallel_map(
            lambda d: (d, doiorg.fetch_citation_string(session, d)),
            todo, workers=min(args.workers, 4))
        for pub_doi, citation in fetched:
            store.put_citation_string(conn, pub_doi, citation)
        conn.commit()

    kept = kept.copy()
    kept["pub_citation_str"] = kept["pub_doi"].apply(
        lambda d: (store.get_citation_string(conn, d) or "error occurred")
        if isinstance(d, str) and d.startswith("10.") else "not a doi")

    final = export_mod.finalize(
        kept, previous_csv=os.path.join(args.results, "latest_results.csv"))
    csv_path, json_path, filtered_path = export_mod.write_outputs(
        final, filtered_out, results_dir=args.results)
    store.log(conn, "export", "Results written", len(final))
    print(f"[export] wrote {csv_path}, {json_path}, {filtered_path}")


STEPS = {"dois": _dois, "fetch": _fetch, "enrich": _enrich, "export": _export}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="citations", description=__doc__)
    parser.add_argument("command", choices=[*STEPS, "all"])
    parser.add_argument("--db", default=os.environ.get("CITATIONS_DB", "citations.db"))
    parser.add_argument("--results", default="Results/v3")
    parser.add_argument("--workers", type=int, default=6,
                        help="parallel HTTP workers per network-bound step")
    parser.add_argument("--limit", type=int,
                        help="only process the first N items (smoke tests)")
    parser.add_argument("--source", action="append",
                        choices=["datacite", "scholix", "overton"],
                        help="restrict `fetch` to specific sources")
    parser.add_argument("--no-fetch", action="store_true",
                        help="export: use only cached citation strings")
    args = parser.parse_args(argv)

    conn = store.connect(args.db)
    session = make_session()
    commands = ["dois", "fetch", "enrich", "export"] if args.command == "all" \
        else [args.command]
    for command in commands:
        STEPS[command](conn, session, args)


if __name__ == "__main__":
    main()
