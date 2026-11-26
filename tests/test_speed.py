"""Rate limits, parallel harvests and parallel citation strings."""

import threading
import time
from types import SimpleNamespace

import pytest

from citations import citation_text, db, works
from citations.harvest import run_harvest, run_harvests
from citations.http import HttpClient, Limit, bucket_for, throttled_count
from citations.inventory import run_inventory
from citations.works import run_works

from conftest import make_ctx
from test_pipeline import FakeFormatter, World

SOURCES = ("datacite", "scholexplorer", "overton", "crossref")


# -- rate limits ----------------------------------------------------------------
def test_published_limits_depend_on_a_contact_email():
    """The rate limits sit under each API's published limit, and are higher with a contact email."""
    polite, public = HttpClient(mailto="x@example.org").limits, HttpClient().limits
    assert polite["api.crossref.org/list"].concurrent == 3 and polite["api.crossref.org/list"].rate < 3
    assert polite["api.crossref.org/single"].rate < 10
    assert public["api.crossref.org/list"].concurrent == 1 and public["api.crossref.org/list"].rate < 1
    assert polite["api.datacite.org"].rate * 300 < 1000 and public["api.datacite.org"].rate * 300 < 500
    assert polite["app.overton.io"].rate < 1


@pytest.mark.parametrize("url, bucket", [
    ("https://api.crossref.org/works/10.1234/abc", "api.crossref.org/single"),
    ("https://api.crossref.org/beta/datacitations/", "api.crossref.org/list"),
    ("https://api.crossref.org/works?filter=from-pub-date:2020", "api.crossref.org/list"),
    ("https://api.datacite.org/events", "api.datacite.org"),
    ("https://api.scholexplorer.openaire.eu/v3/Links", "api.scholexplorer.openaire.eu"),
])
def test_bucket_for(url, bucket):
    """Each URL falls in its API's rate-limit bucket, with Crossref single records and lists apart."""
    assert bucket_for(url) == bucket


def test_a_slow_api_does_not_hold_up_the_others():
    """Waiting for a slow API's rate limit does not delay requests to a fast one."""
    client = HttpClient(limits={"slow": Limit(2, 1, "slow"), "fast": Limit(200, 4, "fast")})
    done = {}

    def use(bucket, n):
        """Make `n` requests in `bucket` and record how long they took.

        Args:
            bucket: The rate-limit bucket.
            n: How many requests.
        """
        start = time.monotonic()
        for _ in range(n):
            with client.limited(bucket):
                pass
        done[bucket] = time.monotonic() - start

    threads = [threading.Thread(target=use, args=("slow", 3))] + \
              [threading.Thread(target=use, args=("fast", 10)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert done["slow"] >= 0.9          # 3 requests at 2 a second
    assert done["fast"] < 0.5           # not queued behind the slow API's sleeps


def test_requests_at_once_are_capped_per_group():
    """Buckets in the same group share one cap on requests in flight."""
    client = HttpClient(limits={"a": Limit(1000, 2, "shared"), "b": Limit(1000, 2, "shared")})
    lock, state = threading.Lock(), {"now": 0, "max": 0}

    def use(bucket):
        """Hold a slot in `bucket` briefly, recording the most slots held at once.

        Args:
            bucket: The rate-limit bucket.
        """
        with client.limited(bucket):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1

    threads = [threading.Thread(target=use, args=("a" if i % 2 else "b",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["max"] == 2


def _response(status, retried_statuses):
    """A fake response with a retry history.

    Args:
        status: The final status code.
        retried_statuses: The status of each retried response.

    Returns:
        An object shaped like a `requests.Response` for
        `citations.http.throttled_count`.
    """
    history = tuple(SimpleNamespace(status=s) for s in retried_statuses)
    return SimpleNamespace(status_code=status, raw=SimpleNamespace(retries=SimpleNamespace(history=history)))


def test_429s_are_counted_including_retries(monkeypatch):
    """429 responses are counted, retries included, and the client totals them by bucket."""
    assert throttled_count(_response(200, [429, 503, 429])) == 2
    assert throttled_count(_response(429, [429])) == 2
    assert throttled_count(SimpleNamespace(status_code=200)) == 0

    client = HttpClient(limits={})
    session = SimpleNamespace(request=lambda method, url, **kw: _response(200, [429, 429]))
    monkeypatch.setattr(client, "_session", lambda: session)
    client.get("https://api.datacite.org/dois/10.5285/x")
    assert client.throttled() == {"api.datacite.org": 2}


# -- parallel harvests ------------------------------------------------------------
def _harvested(con):
    """Every raw link in a store, sorted, for comparing two stores.

    Args:
        con: The store connection.

    Returns:
        The links as tuples.
    """
    return sorted(tuple(r) for r in con.execute(
        "SELECT source, data_doi, citing_id, relation_type, source_relation, provenance FROM raw_links"))


def _store(tmp_path, name, settings):
    """A new store with the fake world's inventory in it.

    Args:
        tmp_path: The test's temporary folder.
        name: The store's file name.
        settings: Settings to copy, with the new store path.

    Returns:
        ``(settings, con)``.
    """
    s = type(settings)(**{**settings.__dict__, "db_path": tmp_path / name})
    con = db.connect(s.db_path)
    assert run_inventory(con, World().client(), s.client_id) == "success"
    return s, con


def test_parallel_harvest_gives_the_same_links_as_one_at_a_time(tmp_path, settings):
    """Harvesting the sources together gives exactly the links of harvesting them one at a time."""
    one_s, one = _store(tmp_path, "one.sqlite", settings)
    for source in SOURCES:
        assert run_harvest(make_ctx(one, World().client(), one_s), source) == "success"
    all_s, together = _store(tmp_path, "all.sqlite", settings)
    assert set(run_harvests(all_s, World().client(), SOURCES).values()) == {"success"}
    assert _harvested(together) == _harvested(one) != []


def test_the_sources_really_are_harvested_at_the_same_time(tmp_path, settings):
    # Each source's first request waits until all four have made one: one at a time, it would time out.
    """The sources run at the same time: each one's first request waits for all four, which would time out in sequence."""
    s, _ = _store(tmp_path, "s.sqlite", settings)
    barrier, seen, lock = threading.Barrier(len(SOURCES), timeout=10), set(), threading.Lock()
    client = World().client()
    get_json, post_json = client.get_json, client.post_json

    def first_waits(host):
        """Wait at the barrier on the first request to `host`.

        Args:
            host: The request's host.
        """
        with lock:
            first = host not in seen
            seen.add(host)
        if first:
            barrier.wait()

    def get(url, params=None, headers=None, allow_404=True):
        """The fake GET, waiting at the barrier first.

        Args:
            url: The request URL.
            params: Query parameters.
            headers: Request headers.
            allow_404: Passed on.

        Returns:
            The fake client's answer.
        """
        first_waits(url.split("/")[2])
        return get_json(url, params, headers, allow_404)

    def post(url, data=None, headers=None):
        """The fake POST, waiting at the barrier first.

        Args:
            url: The request URL.
            data: The form data.
            headers: Request headers.

        Returns:
            The fake client's answer.
        """
        first_waits(url.split("/")[2])
        return post_json(url, data, headers)

    client.get_json, client.post_json = get, post
    assert set(run_harvests(s, client, SOURCES).values()) == {"success"}


# -- citation strings ---------------------------------------------------------------
def test_parallel_citation_strings_match_sequential():
    """Citation strings fetched in parallel through a limiter match those fetched one at a time."""
    rows = [{"pub_doi": f"10.1234/w{i}", "pub_title": f"Work {i}", "bucket": "doi.org/crossref" if i % 2 else
             "doi.org/datacite"} for i in range(30)] + [{"pub_doi": None, "pub_title": "A web page"}]
    used = []

    class Limiter:
        """A limiter that records the bucket of each request."""

        def limited(self, bucket):
            """Record the bucket and return a context manager.

            Args:
                bucket: The rate-limit bucket.

            Returns:
                Any context manager.
            """
            used.append(bucket)
            return threading.Lock()   # any context manager

        def observe(self, bucket, response):
            """Ignore the response.

            Args:
                bucket: The rate-limit bucket.
                response: The response.
            """

    one = citation_text.format_citations(rows, session=FakeFormatter(), pause=0, workers=1)
    many = citation_text.format_citations(rows, session=FakeFormatter(), pause=0, workers=4, limiter=Limiter())
    assert one == many
    assert sorted(set(used)) == ["doi.org/crossref", "doi.org/datacite"] and len(used) == 30


@pytest.fixture
def harvested(tmp_path, settings):
    """A store with the inventory and every source harvested from the fake world.

    Returns:
        ``(settings, con)``.
    """
    s, con = _store(tmp_path, "w.sqlite", settings)
    assert set(run_harvests(s, World().client(), SOURCES).values()) == {"success"}
    return s, con


def test_works_are_saved_as_they_arrive(harvested, monkeypatch):
    """A works run stopped part-way keeps what it saved, and the next run finishes the rest."""
    settings, con = harvested
    monkeypatch.setattr(works, "SAVE_EVERY", 2)
    monkeypatch.setattr(citation_text, "_session", lambda: FakeFormatter())
    real = works.format_citations
    calls = []

    def stops_after_two_chunks(rows, **kw):
        """Format citations for two chunks, then fail as if the job had run out of time.

        Args:
            rows: The chunk's citation rows.
            **kw: Passed on to the real ``format_citations``.

        Returns:
            What the real ``format_citations`` returns.

        Raises:
            RuntimeError: On the third chunk.
        """
        calls.append(len(rows))
        if len(calls) > 2:
            raise RuntimeError("the job ran out of time")
        return real(rows, **kw)

    monkeypatch.setattr(works, "format_citations", stops_after_two_chunks)
    assert run_works(con, World().client(), settings) == "failed"
    saved = con.execute("SELECT COUNT(*) FROM works WHERE citation_text IS NOT NULL").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    assert saved == 4 and total > 4             # two chunks of citations kept, all metadata kept

    monkeypatch.setattr(works, "format_citations", real)
    assert run_works(con, World().client(), settings) == "success"
    assert con.execute("SELECT COUNT(*) FROM works WHERE citation_text IS NULL").fetchone()[0] == 0


# -- progress -----------------------------------------------------------------------
def test_results_arrive_as_they_finish():
    """``HttpClient.map`` yields results as they finish, not in input order."""
    client = HttpClient(workers=2, limits={})

    def slow_first(i):
        """Return the item, slowly for the first one.

        Args:
            i: The item.

        Returns:
            The item.
        """
        time.sleep(0.3 if i == 0 else 0)
        return i

    order = [item for item, _, _ in client.map(slow_first, range(4))]
    assert order[0] != 0 and sorted(order) == [0, 1, 2, 3]


def test_each_source_logs_its_progress(tmp_path, settings, monkeypatch, caplog):
    """Each source logs how many keys it has to fetch and its progress, including 429s."""
    from citations import harvest

    monkeypatch.setattr(harvest, "PROGRESS_SECONDS", 0)
    s, _ = _store(tmp_path, "p.sqlite", settings)
    caplog.set_level("INFO", logger="citations")
    assert set(run_harvests(s, World().client(), SOURCES).values()) == {"success"}
    lines = [r.getMessage() for r in caplog.records]
    assert "scholexplorer: 3 to fetch" in lines
    assert any(line.startswith("scholexplorer: 3/3, ") and "0 rate-limited (429)" in line for line in lines)
    assert any(line.startswith("crossref: 3/3, ") for line in lines)
