"""Command line: ``python -m citations <command>`` (or the ``citations`` script).

    all        inventory, every source, works, merge, publish (the weekly run)
    inventory  every DOI of the DataCite client, checked against DataCite's total
    harvest    one or more sources: datacite scholexplorer overton crossref
    works      metadata and citation strings for the citing works
    merge      combine the sources' latest good harvests into classified links
    publish    write Results/v4 and the v3-compatible copy, if the guards pass
    reconcile  print the comparison with DataCite's citationCount
    status     the latest run of every stage

Exit codes: 0 success, 1 a stage failed, 2 publishing was blocked by a guard.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import db
from .config import ALL_SOURCES, REQUIRED_SOURCES, Settings
from .harvest import NoInventory, run_harvests
from .http import HttpClient
from .inventory import run_inventory
from .merge import run_merge
from .publish import run_publish
from .reconcile import reconcile
from .works import run_works

log = logging.getLogger("citations")


def _annotate(level: str, message: str):
    """Print a GitHub Actions annotation, so a failure shows on the run's summary page.

    Does nothing outside GitHub Actions.

    Args:
        level: ``"error"``, ``"warning"`` or ``"notice"``.
        message: The annotation text.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level}::{message}", flush=True)


def _common(suppress: bool) -> argparse.ArgumentParser:
    """The options every command accepts, before or after the command name.

    Both ``citations --db x status`` and ``citations status --db x`` work: the
    options are added to the main parser with their defaults, and to each
    subcommand with suppressed defaults, so a value given after the command
    overrides one given before it without resetting it.

    Args:
        suppress: Whether to suppress the defaults (for the subcommands).

    Returns:
        A parent parser holding ``--db``, ``--results``, ``--workers``,
        ``--mailto`` and ``--verbose``.
    """
    common = argparse.ArgumentParser(add_help=False)
    default = (lambda value: argparse.SUPPRESS) if suppress else (lambda value: value)
    common.add_argument("--db", type=Path, default=default(Path(os.environ.get("CITATIONS_DB", "data/citations.sqlite"))),
                        help="SQLite store (default data/citations.sqlite)")
    common.add_argument("--results", type=Path, default=default(Path("Results")), help="results folder (default Results)")
    common.add_argument("--workers", type=int, default=default(int(os.environ.get("CITATIONS_WORKERS", "4"))),
                        help="parallel requests per source (default 4)")
    common.add_argument("--mailto", default=default(os.environ.get("CITATIONS_MAILTO")),
                        help="contact email for the Crossref/DataCite polite pools (or CITATIONS_MAILTO)")
    common.add_argument("-v", "--verbose", action="store_true", default=default(False))
    return common


def _source(value: str) -> str:
    # Checked here rather than with choices=: before Python 3.12 argparse also checks the
    # empty default of an nargs="*" positional against choices, so `harvest` alone failed.
    """Check a source name given to ``harvest``.

    This is checked here rather than with ``choices=``: before Python 3.12
    argparse also checks the empty default of an ``nargs="*"`` positional
    against ``choices``, so ``harvest`` with no sources failed.

    Args:
        value: The name as typed.

    Returns:
        The name, unchanged.

    Raises:
        argparse.ArgumentTypeError: If it is not one of
            `citations.config.ALL_SOURCES`.
    """
    if value not in ALL_SOURCES:
        raise argparse.ArgumentTypeError(f"invalid choice: {value!r} (choose from {', '.join(ALL_SOURCES)})")
    return value


def _accept_drop(parser: argparse.ArgumentParser):
    """Add the ``--accept-drop SOURCE ...`` option to a subcommand.

    Args:
        parser: The subcommand's parser.
    """
    parser.add_argument("--accept-drop", nargs="+", default=[], choices=ALL_SOURCES, metavar="SOURCE",
                        help="accept a drop of more than 20%% in these sources' links (when it is real): "
                             "the harvest is not rejected and publishing is not blocked for it")


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser, with every subcommand and its options.

    Returns:
        The parser. Its help text is this module's docstring.
    """
    parser = argparse.ArgumentParser(prog="citations", description=__doc__, parents=[_common(False)],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    _add_parser = sub.add_parser
    sub.add_parser = lambda name, **kw: _add_parser(name, parents=[_common(True)], **kw)

    p_all = sub.add_parser("all", help="the full weekly run")
    p_all.add_argument("--skip", nargs="*", default=[], choices=ALL_SOURCES, help="sources not to harvest this time")
    p_all.add_argument("--snapshot", type=Path, help="read the inventory from a saved DataCite snapshot (.json.gz)")
    p_all.add_argument("--save-snapshot", type=Path, help="save the DataCite records the inventory downloads")
    p_all.add_argument("--force", action="store_true", help="publish even if a guard fails (recorded in the manifest)")
    p_all.add_argument("--no-resume", action="store_true", help="start every harvest afresh")
    _accept_drop(p_all)

    p_inv = sub.add_parser("inventory", help="every DOI of the DataCite client")
    p_inv.add_argument("--snapshot", type=Path)
    p_inv.add_argument("--save-snapshot", type=Path)

    p_h = sub.add_parser("harvest", help="harvest sources")
    p_h.add_argument("sources", nargs="*", type=_source, metavar="SOURCE",
                     help=f"default: all of {', '.join(ALL_SOURCES)}")
    p_h.add_argument("--no-resume", action="store_true")
    _accept_drop(p_h)

    sub.add_parser("works", help="metadata and citation strings for citing works")
    sub.add_parser("merge", help="combine harvests into classified links")
    p_pub = sub.add_parser("publish", help="write Results/v4 and Results/v3")
    p_pub.add_argument("--force", action="store_true")
    p_pub.add_argument("--no-v3", action="store_true", help="do not write the v3-compatible files")
    _accept_drop(p_pub)
    sub.add_parser("reconcile", help="compare with DataCite's citationCount")
    sub.add_parser("status", help="latest run of every stage")
    return parser


def _status(con) -> int:
    """Print the latest run of every stage and source, then each source's good run.

    Args:
        con: An open store connection.

    Returns:
        The exit code, always 0.
    """
    rows = con.execute(
        "SELECT r.* FROM runs r JOIN (SELECT stage, COALESCE(source, '') AS s, MAX(run_id) AS m FROM runs "
        "GROUP BY stage, COALESCE(source, '')) x ON r.run_id = x.m ORDER BY r.run_id").fetchall()
    for r in rows:
        name = f"{r['stage']}{':' + r['source'] if r['source'] else ''}"
        throttled = (db.loads(r["details"], {}) or {}).get("throttled_429")
        print(f"{name:24} run {r['run_id']:<5} {r['status']:9} {r['started_at']} -> {r['finished_at'] or '…'}  "
              f"rows={r['rows']}  errors={r['errors']}"
              f"{f'  429s={throttled}' if throttled is not None else ''}  {r['message'] or ''}")
    for s in con.execute("SELECT * FROM source_state ORDER BY source"):
        print(f"good {s['source']:19} run {s['good_run_id']:<5} {s['good_finished_at']}  rows={s['rows']}")
    return 0


def main(argv=None) -> int:
    """Run a command and return its exit code.

    Args:
        argv: The arguments, without the program name; ``sys.argv[1:]`` when
            None.

    Returns:
        0 on success; 1 when a stage failed; 2 when publishing was blocked by a
        guard. ``all`` returns 0 when it published, even if an optional stage
        failed (a warning annotation says which).
    """
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings(db_path=args.db, results_dir=args.results, workers=args.workers,
                        accept_drop=frozenset(getattr(args, "accept_drop", [])))
    if args.mailto:
        settings.mailto = args.mailto
    con = db.connect(settings.db_path)
    client = HttpClient(mailto=settings.mailto, workers=settings.workers)

    if args.command == "status":
        return _status(con)
    if args.command == "reconcile":
        rows, summary = reconcile(con)
        for key, value in summary.items():
            print(f"{key:30} {value}")
        for row in rows[:20]:
            if row["missing_vs_datacite"]:
                print(f"  {row['doi']}  DataCite {row['datacite_citation_count']}, harvested "
                      f"{row['datacite_links_harvested']}")
        return 0
    if args.command == "inventory":
        return 0 if run_inventory(con, client, settings.client_id, args.snapshot, args.save_snapshot) == "success" else 1
    if args.command == "harvest":
        try:
            statuses = run_harvests(settings, client, args.sources or ALL_SOURCES, resume=not args.no_resume)
        except NoInventory as error:
            log.error("%s", error)
            return 1
        return 0 if all(v in ("success", "skipped") for v in statuses.values()) else 1
    if args.command == "works":
        return 0 if run_works(con, client, settings) in ("success", "partial") else 1
    if args.command == "merge":
        return 0 if run_merge(con, settings) == "success" else 1
    if args.command == "publish":
        settings.write_v3 = not args.no_v3
        status = run_publish(con, settings, force=args.force)
        return {"success": 0, "blocked": 2}.get(status, 1)

    # all
    failed = []
    if run_inventory(con, client, settings.client_id, args.snapshot, args.save_snapshot) != "success":
        failed.append("inventory")
        _annotate("error", "Inventory failed; harvesting with the last good inventory if there is one.")
        if db.good_run(con, "inventory") is None:
            return 1
    sources = [s for s in ALL_SOURCES if s not in args.skip]
    for source, status in run_harvests(settings, client, sources, resume=not args.no_resume).items():
        if status not in ("success", "skipped"):
            failed.append(source)
            _annotate("error" if source in REQUIRED_SOURCES else "warning",
                      f"{source} harvest {status}; its last good harvest is used if recent enough.")
    if run_works(con, client, settings) == "failed":
        failed.append("works")
        _annotate("error", "Citing-work metadata stage failed.")
    if run_merge(con, settings) != "success":
        _annotate("error", "Merge failed; nothing published.")
        return 1
    status = run_publish(con, settings, force=args.force)
    if status == "blocked":
        latest = db.latest_run(con, "publish")
        _annotate("error", f"Publishing blocked: {latest['message']}")
        return 2
    if failed:
        _annotate("warning", f"Published, but these stages did not succeed: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
