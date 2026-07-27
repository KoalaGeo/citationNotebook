"""SQLite working store.

Replaces the .pkl intermediates (which pinned pandas: pickles break across
versions) with one file of real typed tables. It also gives the pipeline
incremental behaviour for free:

  * citations PRIMARY KEY (data_doi, pub_doi, source_id) -> dedupe by upsert
  * pub_info / citation_strings are per-DOI caches, so weekly runs only hit
    doi.org / citation.doi.org for NEW publications (the two slowest steps)
  * fetch_log answers "why is citation X missing?" (issue #11) with one query

The .db file is a build cache, not a source of truth: delete it and the next
run rebuilds everything from the APIs.
"""

import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    data_doi          TEXT PRIMARY KEY,
    publisher         TEXT,
    title             TEXT,
    publication_year  INTEGER,
    authors           TEXT            -- JSON list
);
CREATE TABLE IF NOT EXISTS citations (
    data_doi      TEXT NOT NULL,
    pub_doi       TEXT NOT NULL,      -- bare DOI, or a plain URL (Overton)
    source_id     TEXT NOT NULL,      -- e.g. datacite-crossref / scholex / overton
    source_group  TEXT NOT NULL,      -- datacite | scholex | overton (dedupe priority)
    relation_type TEXT,
    pub_title     TEXT,
    pub_date      TEXT,
    pub_authors   TEXT,               -- JSON (list, or a string sentinel)
    pub_type      TEXT,
    pub_publisher TEXT,
    first_seen    TEXT,
    PRIMARY KEY (data_doi, pub_doi, source_group)
);
CREATE TABLE IF NOT EXISTS pub_info (            -- doi.org content-negotiation cache
    pub_doi    TEXT PRIMARY KEY,
    title      TEXT,
    date       TEXT,
    authors    TEXT,                              -- JSON
    publisher  TEXT,
    type       TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS citation_strings (    -- citation.doi.org cache
    pub_doi    TEXT PRIMARY KEY,
    citation   TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS fetch_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at   TEXT,
    source   TEXT,
    detail   TEXT,
    n_items  INTEGER,
    n_errors INTEGER
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# --- datasets ---------------------------------------------------------------

def upsert_datasets(conn, records):
    conn.executemany(
        "INSERT INTO datasets (data_doi, publisher, title, publication_year, authors)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(data_doi) DO UPDATE SET publisher=excluded.publisher,"
        " title=excluded.title, publication_year=excluded.publication_year,"
        " authors=excluded.authors",
        [(r["data_doi"], r["publisher"], r["title"], r["publication_year"],
          json.dumps(r["authors"], ensure_ascii=False)) for r in records])
    conn.commit()


def load_datasets(conn):
    out = {}
    for row in conn.execute("SELECT * FROM datasets"):
        out[row["data_doi"]] = {
            "data_doi": row["data_doi"],
            "data_publisher": row["publisher"],
            "data_title": row["title"],
            "data_publication_year": row["publication_year"],
            "data_authors": json.loads(row["authors"]) if row["authors"] else [],
        }
    return out


def dataset_dois(conn):
    return [r["data_doi"] for r in conn.execute("SELECT data_doi FROM datasets ORDER BY data_doi")]


# --- citations --------------------------------------------------------------

def upsert_citations(conn, source_group, rows):
    """Insert rows; re-running a source refreshes its own rows in place."""
    conn.executemany(
        "INSERT INTO citations (data_doi, pub_doi, source_id, source_group,"
        " relation_type, pub_title, pub_date, pub_authors, pub_type,"
        " pub_publisher, first_seen)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(data_doi, pub_doi, source_group) DO UPDATE SET"
        " source_id=excluded.source_id, relation_type=excluded.relation_type,"
        " pub_title=excluded.pub_title, pub_date=excluded.pub_date,"
        " pub_authors=excluded.pub_authors, pub_type=excluded.pub_type,"
        " pub_publisher=excluded.pub_publisher",
        [(r["data_doi"], r["pub_doi"], r.get("source_id", source_group),
          source_group, r.get("relation_type"), r.get("pub_title"),
          r.get("pub_date"), json.dumps(r.get("pub_authors"), ensure_ascii=False),
          r.get("pub_type"), r.get("pub_publisher"), now()) for r in rows])
    conn.commit()


def clear_source(conn, source_group):
    conn.execute("DELETE FROM citations WHERE source_group = ?", (source_group,))
    conn.commit()


def load_citations(conn):
    rows = []
    for row in conn.execute("SELECT * FROM citations"):
        rec = dict(row)
        try:
            rec["pub_authors"] = json.loads(rec["pub_authors"])
        except (TypeError, ValueError):
            pass
        rows.append(rec)
    return rows


# --- per-DOI caches ----------------------------------------------------------

def get_pub_info(conn, pub_doi):
    row = conn.execute("SELECT * FROM pub_info WHERE pub_doi = ?", (pub_doi,)).fetchone()
    if not row:
        return None
    info = dict(row)
    try:
        info["authors"] = json.loads(info["authors"])
    except (TypeError, ValueError):
        pass
    return info


def put_pub_info(conn, pub_doi, info):
    conn.execute(
        "INSERT OR REPLACE INTO pub_info (pub_doi, title, date, authors,"
        " publisher, type, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (pub_doi, info.get("title"), info.get("date"),
         json.dumps(info.get("authors"), ensure_ascii=False),
         info.get("publisher"), info.get("type"), now()))


def missing_pub_info(conn, pub_dois):
    have = {r["pub_doi"] for r in conn.execute("SELECT pub_doi FROM pub_info")}
    return [d for d in pub_dois if d not in have]


def get_citation_string(conn, pub_doi):
    row = conn.execute("SELECT citation FROM citation_strings WHERE pub_doi = ?",
                       (pub_doi,)).fetchone()
    return row["citation"] if row else None


def put_citation_string(conn, pub_doi, citation):
    conn.execute("INSERT OR REPLACE INTO citation_strings (pub_doi, citation,"
                 " fetched_at) VALUES (?, ?, ?)", (pub_doi, citation, now()))


def missing_citation_strings(conn, pub_dois):
    have = {r["pub_doi"] for r in conn.execute("SELECT pub_doi FROM citation_strings")}
    return [d for d in pub_dois if d not in have]


# --- log ---------------------------------------------------------------------

def log(conn, source, detail, n_items, n_errors=0):
    conn.execute("INSERT INTO fetch_log (run_at, source, detail, n_items, n_errors)"
                 " VALUES (?, ?, ?, ?, ?)", (now(), source, detail, n_items, n_errors))
    conn.commit()
