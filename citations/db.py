"""SQLite store for every stage's intermediate data.

One file (``data/citations.sqlite`` by default) replaces the pickles in
``Results/intermediate_data``. Each harvest is a *run*; a source's links are
only used once its run finishes successfully, and ``source_state`` points at
the latest good run, so a failed or partial harvest never replaces good data.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import CODE_VERSION

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    stage        TEXT NOT NULL,     -- inventory | harvest | works | merge | publish
    source       TEXT,              -- harvest only: datacite | scholexplorer | overton | crossref
    status       TEXT NOT NULL,     -- running | success | partial | failed | rejected | skipped | blocked
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    rows         INTEGER,
    items        INTEGER,           -- DOIs (or other keys) queried
    errors       INTEGER,
    message      TEXT,
    details      TEXT,              -- JSON
    code_version TEXT
);

CREATE TABLE IF NOT EXISTS source_state (
    source           TEXT PRIMARY KEY,   -- 'inventory' or a harvest source
    good_run_id      INTEGER NOT NULL,
    good_finished_at TEXT NOT NULL,
    rows             INTEGER
);

CREATE TABLE IF NOT EXISTS datasets (
    doi                     TEXT PRIMARY KEY,
    data_centre             TEXT,
    publisher               TEXT,
    title                   TEXT,
    publication_year        INTEGER,
    resource_type_general   TEXT,
    registered              TEXT,
    authors                 TEXT,       -- JSON list of {name, given, family, orcid}
    datacite_citation_count INTEGER,
    run_id                  INTEGER
);
CREATE TABLE IF NOT EXISTS datasets_new AS SELECT * FROM datasets WHERE 0;

CREATE TABLE IF NOT EXISTS dataset_relations (
    doi           TEXT NOT NULL,
    relation_type TEXT,                 -- DataCite relationType, from the dataset's side
    related_raw   TEXT,
    related_type  TEXT,                 -- DataCite relatedIdentifierType
    run_id        INTEGER
);
CREATE TABLE IF NOT EXISTS dataset_relations_new AS SELECT * FROM dataset_relations WHERE 0;
CREATE INDEX IF NOT EXISTS dataset_relations_doi ON dataset_relations (doi);

CREATE TABLE IF NOT EXISTS raw_links (
    source          TEXT NOT NULL,
    run_id          INTEGER NOT NULL,
    data_doi        TEXT NOT NULL,
    citing_id       TEXT NOT NULL,
    citing_id_type  TEXT NOT NULL,      -- doi | url | pmid | pmc | handle
    relation_type   TEXT NOT NULL,      -- DataCite vocabulary, from the dataset's side
    source_relation TEXT NOT NULL,      -- the relation exactly as the source reported it
    provenance      TEXT NOT NULL,      -- finer origin, e.g. a DataCite event source-id
    hint            TEXT,               -- JSON: what the source said about the citing work
    PRIMARY KEY (source, run_id, data_doi, citing_id, source_relation, provenance)
);
CREATE INDEX IF NOT EXISTS raw_links_run ON raw_links (source, run_id);

CREATE TABLE IF NOT EXISTS fetch_log (
    source     TEXT NOT NULL,
    run_id     INTEGER NOT NULL,
    key        TEXT NOT NULL,
    status     TEXT NOT NULL,           -- ok | error
    n          INTEGER,
    message    TEXT,
    fetched_at TEXT,
    PRIMARY KEY (source, run_id, key)
);

CREATE TABLE IF NOT EXISTS works (
    citing_id           TEXT PRIMARY KEY,
    citing_id_type      TEXT,
    title               TEXT,
    work_type           TEXT,           -- Crossref type (citations/worktypes.py)
    container_title     TEXT,
    publisher           TEXT,
    issued              TEXT,           -- ISO 8601: YYYY, YYYY-MM or YYYY-MM-DD
    issued_precision    TEXT,           -- year | month | day
    authors             TEXT,           -- JSON list of {name, given, family, orcid}
    citation_text       TEXT,
    citation_source     TEXT,           -- formatter | reused | fallback | link
    metadata_source     TEXT,           -- crossref | datacite | inventory | scholexplorer | overton | crossref-datacitations
    fetched_at          TEXT,
    citation_fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS links (
    link_id          TEXT PRIMARY KEY,
    data_doi         TEXT NOT NULL,
    data_centre      TEXT,
    citing_id        TEXT NOT NULL,
    citing_id_type   TEXT NOT NULL,
    relation_type    TEXT NOT NULL,
    relation_class   TEXT NOT NULL,
    counted          INTEGER NOT NULL,
    status           TEXT NOT NULL,
    exclusion_reason TEXT,
    sources          TEXT NOT NULL,     -- JSON list
    source_relations TEXT NOT NULL,     -- JSON object: source -> [raw relations]
    first_seen       TEXT NOT NULL,
    last_seen        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS link_history (
    link_id    TEXT PRIMARY KEY,
    data_doi   TEXT NOT NULL,
    citing_id  TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
"""


def now_iso() -> str:
    """The current UTC time as an ISO 8601 string to the second.

    Returns:
        For example ``"2026-11-26T01:17:00Z"``. Every timestamp in the store is
        written in this form.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    """Parse a timestamp written by `now_iso`.

    Args:
        value: An ISO 8601 timestamp, with ``Z`` or an offset, or None.

    Returns:
        A timezone-aware datetime, or None when `value` is empty.
    """
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def age_days(value: str | None, now: datetime | None = None) -> float | None:
    """How many days ago a timestamp was.

    Args:
        value: An ISO 8601 timestamp, or None.
        now: The time to measure from; the current UTC time when None.

    Returns:
        The age in days (fractional), or None when `value` is empty.
    """
    then = parse_iso(value)
    if then is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - then).total_seconds() / 86400


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the store, creating the file, its folder and its tables if needed.

    The connection returns rows as `sqlite3.Row`, so columns can be read
    by name. Each harvest thread opens its own connection; a writer waits up to
    60 seconds for another thread's transaction to finish.

    Args:
        path: The SQLite file, or ``":memory:"`` for a throwaway store.

    Returns:
        An open connection with the schema in place.
    """
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    # Sources are harvested in parallel, one connection per thread; each writes in short
    # transactions, so a writer waits at most briefly for another (timeout in seconds).
    con = sqlite3.connect(str(path), timeout=60)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
    _crossref_work_types(con)
    con.commit()
    return con


def _crossref_work_types(con):
    """Map cached work types to Crossref's vocabulary, once per store.

    Stores written before work types were normalised hold each source's own type
    names. This rewrites them with `citations.worktypes.crossref_type` and
    records in ``meta`` that it has done so, so it never runs twice.

    Args:
        con: An open store connection.
    """
    if con.execute("SELECT 1 FROM meta WHERE key='work_type_vocabulary' AND value='crossref'").fetchone():
        return
    from .worktypes import crossref_type

    rows = con.execute("SELECT citing_id, work_type, metadata_source FROM works WHERE work_type IS NOT NULL").fetchall()
    con.executemany("UPDATE works SET work_type=? WHERE citing_id=?",
                    [(crossref_type(r["work_type"], r["metadata_source"]), r["citing_id"]) for r in rows])
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('work_type_vocabulary', 'crossref')")


@contextmanager
def transaction(con: sqlite3.Connection):
    """Run a block as one transaction: commit at the end, roll back on any error.

    Args:
        con: An open store connection.

    Yields:
        The same connection.

    Example:
        ```python
        with db.transaction(con):
            db.set_good_run(con, source, run_id, rows)
            db.prune_harvests(con, source, run_id)
        ```
    """
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise


def start_run(con, stage: str, source: str | None = None) -> int:
    """Record the start of a stage (or one source's harvest) in ``runs``.

    Args:
        con: An open store connection.
        stage: ``inventory``, ``harvest``, ``works``, ``merge`` or ``publish``.
        source: For a harvest, the source being harvested.

    Returns:
        The new run's id.
    """
    cur = con.execute(
        "INSERT INTO runs (stage, source, status, started_at, code_version) VALUES (?, ?, 'running', ?, ?)",
        (stage, source, now_iso(), CODE_VERSION),
    )
    con.commit()
    return cur.lastrowid


def finish_run(con, run_id: int, status: str, rows=None, items=None, errors=None, message=None, details=None):
    """Record how a run ended.

    Args:
        con: An open store connection.
        run_id: The run, from `start_run`.
        status: ``success``, ``partial``, ``failed``, ``rejected``, ``skipped``
            or ``blocked``.
        rows: Rows the run produced (links, datasets, works ...).
        items: Requests or keys the run worked through.
        errors: How many of those failed.
        message: A short explanation, shown in ``status`` and the logs.
        details: Anything else worth keeping, stored as JSON.
    """
    con.execute(
        "UPDATE runs SET status=?, finished_at=?, rows=?, items=?, errors=?, message=?, details=? WHERE run_id=?",
        (status, now_iso(), rows, items, errors, message,
         json.dumps(details, sort_keys=True) if details is not None else None, run_id),
    )
    con.commit()


def get_run(con, run_id: int):
    """One run by id.

    Args:
        con: An open store connection.
        run_id: The run to read.

    Returns:
        The ``runs`` row, or None if there is no such run.
    """
    return con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()


def latest_run(con, stage: str, source: str | None = None):
    """The most recent run of a stage, whatever its status.

    Args:
        con: An open store connection.
        stage: The stage name.
        source: For a harvest, limit to this source.

    Returns:
        The ``runs`` row, or None if the stage has never run.
    """
    if source is None:
        return con.execute("SELECT * FROM runs WHERE stage=? ORDER BY run_id DESC LIMIT 1", (stage,)).fetchone()
    return con.execute(
        "SELECT * FROM runs WHERE stage=? AND source=? ORDER BY run_id DESC LIMIT 1", (stage, source)
    ).fetchone()


def resumable_run(con, source: str, window_days: float):
    """An unfinished harvest of `source` young enough to resume.

    Args:
        con: An open store connection.
        source: The harvest source.
        window_days: The oldest a run may be, by its start time, to be resumed.

    Returns:
        The ``runs`` row of the latest harvest when it is still ``running``
        (interrupted) or ``partial`` and started within `window_days`, else None.
    """
    row = latest_run(con, "harvest", source)
    if row is None or row["status"] not in ("running", "partial"):
        return None
    age = age_days(row["started_at"])
    return row if age is not None and age <= window_days else None


def good_run(con, source: str):
    """The run whose data is currently in use for a source.

    Args:
        con: An open store connection.
        source: ``inventory`` or a harvest source.

    Returns:
        The ``source_state`` row (``good_run_id``, ``good_finished_at``,
        ``rows``), or None if the source has never succeeded.
    """
    return con.execute("SELECT * FROM source_state WHERE source=?", (source,)).fetchone()


def set_good_run(con, source: str, run_id: int, rows: int | None):
    """Point a source at a new good run. The caller commits.

    Args:
        con: An open store connection.
        source: ``inventory`` or a harvest source.
        run_id: The run that just succeeded.
        rows: How many rows it produced, used by the next run's row-drop check.
    """
    con.execute(
        "INSERT INTO source_state (source, good_run_id, good_finished_at, rows) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(source) DO UPDATE SET good_run_id=excluded.good_run_id, "
        "good_finished_at=excluded.good_finished_at, rows=excluded.rows",
        (source, run_id, now_iso(), rows),
    )


def prune_harvests(con, source: str, keep_run_id: int):
    """Drop the raw links and fetch logs of a source's older runs. The caller commits.

    Args:
        con: An open store connection.
        source: The harvest source.
        keep_run_id: The good run, whose data is kept.
    """
    con.execute("DELETE FROM raw_links WHERE source=? AND run_id<>?", (source, keep_run_id))
    con.execute("DELETE FROM fetch_log WHERE source=? AND run_id<>?", (source, keep_run_id))


def loads(value, default=None):
    """Decode a JSON column.

    Args:
        value: The column's text, or None.
        default: What to return for an empty column.

    Returns:
        The decoded value, or `default` when `value` is None or empty.
    """
    if value in (None, ""):
        return default
    return json.loads(value)
