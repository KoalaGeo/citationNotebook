"""Shared HTTP plumbing: one place for retries, timeouts, UA, and parallelism.

Every source module gets its session from make_session() so retry/backoff
behaviour is consistent and changeable in one place.
"""

from concurrent.futures import ThreadPoolExecutor
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "nerc-citation-pipeline/1.0 (EDS dataset citations; contact: NERC-EDS)"
DEFAULT_TIMEOUT = 30


def make_session(total_retries=5, backoff=0.5,
                 statuses=(429, 500, 502, 503, 504)):
    session = requests.Session()
    retry = Retry(total=total_retries, backoff_factor=backoff,
                  status_forcelist=list(statuses), allowed_methods=["GET"],
                  raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=32)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = USER_AGENT
    return session


def get_json(session, url, params=None, headers=None, timeout=DEFAULT_TIMEOUT):
    """GET a JSON document; returns (payload, None) or (None, error_string)."""
    try:
        r = session.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        return r.json(), None
    except requests.RequestException as exc:
        return None, f"request error: {exc}"
    except ValueError as exc:
        return None, f"invalid JSON: {exc}"


def parallel_map(fn, items, workers=6):
    """Map fn over items with a bounded thread pool, preserving order.

    The pipeline is network-bound (thousands of small HTTP calls), so a modest
    thread pool converts hours of sequential waiting into minutes without
    hammering any one API (per-source worker counts stay small).
    """
    if workers <= 1 or len(items) <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))
