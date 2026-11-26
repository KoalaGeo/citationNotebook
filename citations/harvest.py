"""Running a source harvest: resume, error rate, row-drop check and the switch to the new good run.

Each source module (`citations.sources`) only knows how to fetch its own
links. This module runs it: it starts or resumes a run, stores links as they
arrive, and when the source is done decides the run's status. Only a
``success`` becomes the source's new good run; anything else leaves the last
good harvest in use.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import db
from .config import ALL_SOURCES, Settings
from .http import HttpClient, redact

log = logging.getLogger(__name__)


class SourceSkipped(Exception):
    """The source cannot run in this environment; not a failure of the data.

    A source raises it from its ``harvest`` function, for example when Overton
    has no API key. The run is recorded as ``skipped``.
    """


class NoInventory(RuntimeError):
    """A harvest was asked for before any inventory had succeeded."""


@dataclass
class Context:
    """What a source needs to harvest: the store, the HTTP client and the settings.

    Attributes:
        con: The store connection for this source's thread.
        client: The shared HTTP client.
        settings: The run's settings.
    """

    con: object
    client: HttpClient
    settings: Settings
    _datasets: list | None = field(default=None, repr=False)

    def datasets(self) -> list:
        """The current inventory: every dataset of the last good inventory run.

        Read once and kept.

        Returns:
            The ``datasets`` rows, ordered by DOI.

        Raises:
            NoInventory: If no inventory has succeeded yet.
        """
        if self._datasets is None:
            if db.good_run(self.con, "inventory") is None:
                raise NoInventory("No successful inventory yet: run `python -m citations inventory` first.")
            self._datasets = self.con.execute("SELECT * FROM datasets ORDER BY doi").fetchall()
        return self._datasets

    def dataset_dois(self) -> set:
        """The DOIs of the current inventory.

        Returns:
            A set of lower-case DOIs.
        """
        return {row["doi"] for row in self.datasets()}


class Tally:
    """Thread-safe counters for what a source dropped or could not map.

    Sources count, for example, links to outgoing relations or identifiers they
    could not normalise, and report the counts in the run's ``details``.
    """

    def __init__(self):
        """Start with every count at zero."""
        import threading
        from collections import Counter

        self._lock = threading.Lock()
        self.counts = Counter()

    def add(self, key: str, n: int = 1):
        """Add to a count.

        Args:
            key: What is being counted.
            n: How much to add.
        """
        with self._lock:
            self.counts[key] += n

    def as_dict(self) -> dict:
        """The counts so far.

        Returns:
            ``{key: count}``, sorted by key.
        """
        with self._lock:
            return dict(sorted(self.counts.items()))


@dataclass
class RawLink:
    """One link as a source reported it, before merging.

    Attributes:
        data_doi: The dataset's lower-case DOI.
        citing_id: The citing work's normalised identifier.
        citing_id_type: ``doi``, ``url``, ``pmid``, ``pmc`` or ``handle``.
        relation_type: The relation from the dataset's side, in the DataCite
            vocabulary.
        source_relation: The relation exactly as the source reported it.
        provenance: A finer origin within the source, such as a DataCite event
            ``source-id``.
        hint: What the source said about the citing work (title, type, date ...),
            used when no better metadata can be fetched.
    """

    data_doi: str
    citing_id: str
    citing_id_type: str
    relation_type: str
    source_relation: str
    provenance: str
    hint: dict | None = None


def write_links(con, source: str, run_id: int, links: list[RawLink]):
    """Store a batch of a run's raw links. Duplicates are ignored. The caller commits.

    Args:
        con: An open store connection.
        source: The harvest source.
        run_id: The harvest run.
        links: The links to store.
    """
    con.executemany(
        "INSERT OR IGNORE INTO raw_links (source, run_id, data_doi, citing_id, citing_id_type, relation_type, "
        "source_relation, provenance, hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (source, run_id, l.data_doi, l.citing_id, l.citing_id_type, l.relation_type, l.source_relation,
             l.provenance, json.dumps(l.hint, ensure_ascii=False, sort_keys=True) if l.hint else None)
            for l in links
        ],
    )


def log_fetch(con, source: str, run_id: int, key: str, status: str, n: int | None = None, message: str | None = None):
    """Record the outcome of one request (or key) in a harvest. The caller commits.

    The fetch log is what makes a harvest resumable: a key logged ``ok`` in a
    run is not fetched again when that run resumes. Logging the same key again
    replaces its entry.

    Args:
        con: An open store connection.
        source: The harvest source.
        run_id: The harvest run.
        key: What was fetched, usually a dataset DOI.
        status: ``ok`` or ``error``.
        n: How many links it gave.
        message: The error, with any API key hidden.
    """
    con.execute(
        "INSERT INTO fetch_log (source, run_id, key, status, n, message, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(source, run_id, key) DO UPDATE SET status=excluded.status, n=excluded.n, "
        "message=excluded.message, fetched_at=excluded.fetched_at",
        (source, run_id, key, status, n, redact(message) if message else None, db.now_iso()),
    )


def done_keys(con, source: str, run_id: int) -> set:
    """The keys already fetched successfully in a run.

    Args:
        con: An open store connection.
        source: The harvest source.
        run_id: The harvest run.

    Returns:
        The set of keys logged ``ok``.
    """
    rows = con.execute("SELECT key FROM fetch_log WHERE source=? AND run_id=? AND status='ok'", (source, run_id))
    return {row["key"] for row in rows}


PROGRESS_SECONDS = 60   # how often each source logs its progress


def _duration(seconds: float) -> str:
    """A rough, readable duration for progress logs.

    Args:
        seconds: The duration.

    Returns:
        ``"under a minute"``, ``"about 12m"`` or ``"about 1h05m"``.
    """
    if seconds < 60:
        return "under a minute"
    minutes = round(seconds / 60)
    return f"about {minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"about {minutes}m"


def per_key(ctx: Context, source: str, run_id: int, keys, fetch_one):
    """Fetch each key in worker threads and store its links as they arrive.

    Keys already fetched in this run are skipped, which is what makes a harvest
    resumable. Each key is committed as it arrives: the other sources are being
    harvested at the same time, so no source holds the store's write lock while
    it waits on the network. Progress is logged every `PROGRESS_SECONDS`.

    Args:
        ctx: The harvest context.
        source: The harvest source.
        run_id: The harvest run.
        keys: Everything to fetch, usually dataset DOIs.
        fetch_one: Called with one key; returns that key's list of
            `RawLink`. An exception is logged as that key's error.

    Returns:
        ``(items, errors)``: keys fetched in this call, and how many failed.
    """
    from .sources import MODULES

    done = done_keys(ctx.con, source, run_id)
    remaining = [k for k in keys if k not in done]
    resumed = len(keys) - len(remaining)
    keys = remaining
    log.info("%s: %d to fetch%s", source, len(keys), f" ({resumed} already fetched in this run)" if resumed else "")
    items = errors = 0
    first_errors = []
    started = last_report = time.monotonic()
    throttled_at_start = _throttled(ctx.client, MODULES[source])

    def report(i):
        """Log progress after `i` keys: rate, errors, 429s and time left.

        Args:
            i: Keys done so far.
        """
        elapsed = time.monotonic() - started
        rate = i / elapsed if elapsed else 0.0
        left = f", {_duration((len(keys) - i) / rate)} left" if rate and i < len(keys) else ""
        log.info("%s: %d/%d, %.1f a second, %d errors, %d rate-limited (429)%s", source, i, len(keys), rate,
                 errors, _throttled(ctx.client, MODULES[source]) - throttled_at_start, left)

    for i, (key, links, error) in enumerate(ctx.client.map(fetch_one, keys), 1):
        items += 1
        if error is not None:
            errors += 1
            if len(first_errors) < 5:
                first_errors.append(f"{key}: {redact(error)}")
            log_fetch(ctx.con, source, run_id, key, "error", message=str(error)[:500])
        else:
            write_links(ctx.con, source, run_id, links)
            log_fetch(ctx.con, source, run_id, key, "ok", n=len(links))
        ctx.con.commit()
        if time.monotonic() - last_report >= PROGRESS_SECONDS:
            report(i)
            last_report = time.monotonic()
    if keys:
        report(items)
    for message in first_errors:
        log.warning("%s: %s", source, message)
    return items, errors


def _throttled(client, module) -> int:
    """429 responses so far from the APIs a source calls.

    Args:
        client: The HTTP client.
        module: The source module; its ``BUCKETS`` names the rate-limit buckets
            it uses.

    Returns:
        The total count of 429 responses in those buckets.
    """
    counts = client.throttled() if hasattr(client, "throttled") else {}
    return sum(counts.get(bucket, 0) for bucket in getattr(module, "BUCKETS", ()))


def run_harvests(settings: Settings, client: HttpClient, sources, resume: bool = True) -> dict:
    """Harvest several sources at the same time, one thread and one store connection each.

    Each source calls a different API with its own rate limit, so running them
    together takes as long as the slowest instead of the sum.

    Args:
        settings: The run's settings.
        client: The shared HTTP client.
        sources: Names of the sources to harvest.
        resume: Whether an unfinished recent run is resumed rather than started
            again.

    Returns:
        ``{source: status}``, as `run_harvest` returns it.
    """
    def one(source):
        """Harvest one source on its own store connection.

        Args:
            source: The source to harvest.

        Returns:
            The run's status.
        """
        con = db.connect(settings.db_path)
        try:
            return run_harvest(Context(con=con, client=client, settings=settings), source, resume=resume)
        finally:
            con.close()

    sources = list(sources)
    if not sources:
        return {}
    with ThreadPoolExecutor(max_workers=len(sources), thread_name_prefix="harvest") as pool:
        futures = {source: pool.submit(one, source) for source in sources}
        return {source: future.result() for source, future in futures.items()}


def run_harvest(ctx: Context, source: str, resume: bool = True) -> str:
    """Harvest one source and decide the run's status.

    The run is:

    - ``skipped`` when the source raised `SourceSkipped`;
    - ``failed`` when it raised anything else;
    - ``partial`` when more than ``max_error_rate`` of its requests failed (the
      next run resumes and retries them);
    - ``rejected`` when it found more than ``max_row_drop`` fewer links than the
      last good harvest, unless the source is in ``accept_drop``;
    - otherwise ``success``, which becomes the source's good run and prunes its
      older runs.

    Args:
        ctx: The harvest context.
        source: The source to harvest; one of
            `citations.config.ALL_SOURCES`.
        resume: Whether an unfinished recent run is resumed.

    Returns:
        The run's status.

    Raises:
        ValueError: If `source` is not a known source.
        NoInventory: If no inventory has succeeded yet.
    """
    from .sources import MODULES

    if source not in ALL_SOURCES:
        raise ValueError(f"Unknown source {source!r}; choose from {', '.join(ALL_SOURCES)}")
    module = MODULES[source]
    con, settings = ctx.con, ctx.settings
    ctx.datasets()  # fail early without an inventory
    throttled_before = _throttled(ctx.client, module)

    previous = db.resumable_run(con, source, settings.resume_window_days) if resume else None
    if previous is not None:
        run_id = previous["run_id"]
        con.execute("UPDATE runs SET status='running' WHERE run_id=?", (run_id,))
        con.commit()
        log.info("%s: resuming run %d started %s", source, run_id, previous["started_at"])
    else:
        run_id = db.start_run(con, "harvest", source)
        log.info("%s: starting run %d", source, run_id)

    try:
        stats = module.harvest(ctx, run_id)
    except SourceSkipped as reason:
        db.finish_run(con, run_id, "skipped", message=str(reason))
        log.warning("%s: skipped (%s)", source, reason)
        return "skipped"
    except Exception as error:  # noqa: BLE001 - recorded, and the stage reports failure
        con.commit()
        db.finish_run(con, run_id, "failed", message=redact(f"{type(error).__name__}: {error}")[:1000])
        log.error("%s: failed: %s", source, redact(error))
        return "failed"

    total_items = con.execute(
        "SELECT COUNT(*) FROM fetch_log WHERE source=? AND run_id=?", (source, run_id)).fetchone()[0]
    total_errors = con.execute(
        "SELECT COUNT(*) FROM fetch_log WHERE source=? AND run_id=? AND status='error'", (source, run_id)).fetchone()[0]
    rows = con.execute("SELECT COUNT(*) FROM raw_links WHERE source=? AND run_id=?", (source, run_id)).fetchone()[0]
    details = dict(stats.get("details", {}))
    details["throttled_429"] = _throttled(ctx.client, module) - throttled_before
    error_rate = total_errors / total_items if total_items else 0.0
    good = db.good_run(con, source)

    if error_rate > settings.max_error_rate:
        status = "partial"
        message = (f"{total_errors} of {total_items} requests failed ({error_rate:.1%}); "
                   "the next run resumes and retries them. Previous good harvest kept.")
    elif good is not None and good["rows"] and rows < good["rows"] * (1 - settings.max_row_drop):
        drop = (f"{rows} links against {good['rows']} in the last good harvest "
                f"(a drop of more than {settings.max_row_drop:.0%})")
        if source in settings.accept_drop:
            status = "success"
            message = f"{drop}, accepted with --accept-drop."
            details["accepted_drop"] = {"previous_rows": good["rows"], "rows": rows}
        else:
            status = "rejected"
            message = (f"{drop}. Previous good harvest kept. If the drop is real, "
                       f"run again with --accept-drop {source}.")
    else:
        status = "success"
        message = None

    if status == "success":
        with db.transaction(con):
            db.set_good_run(con, source, run_id, rows)
            db.prune_harvests(con, source, run_id)
    db.finish_run(con, run_id, status, rows=rows, items=total_items, errors=total_errors, message=message,
                  details=details)
    level = logging.ERROR if status != "success" else logging.WARNING if message else logging.INFO
    log.log(level, "%s: %s, %d links from %d requests (%d errors)%s", source, status, rows, total_items,
            total_errors, f": {message}" if message else "")
    return status
