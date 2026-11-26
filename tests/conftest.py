"""Offline test helpers: a fake HTTP client that answers from Python functions."""

from __future__ import annotations

from urllib.parse import parse_qsl, unquote, urlsplit

import pytest

from citations import db
from citations.config import Settings
from citations.harvest import Context
from citations.http import HttpError


class FakeClient:
    """An offline stand-in for `citations.http.HttpClient`.

    Routes each request to a handler by host and path prefix. A handler is
    called as ``handler(path, params)`` and returns the JSON, returns None for a
    404, or raises. Every request is recorded in ``calls``.
    """

    def __init__(self, routes, mailto=None):
        """Create the client.

        Args:
            routes: ``{(host, path_prefix): handler}``.
            mailto: Contact email, as the real client carries it.
        """
        self.routes = routes        # {(host, path_prefix): handler}
        self.mailto = mailto
        self.calls = []
        self.workers = 1

    def _route(self, url, params):
        """Record a request and answer it from the first matching handler.

        Args:
            url: The request URL; its query string is merged with `params`.
            params: Query parameters or form data.

        Returns:
            The handler's answer.

        Raises:
            AssertionError: If no handler matches, so an unexpected request fails
                the test.
        """
        parts = urlsplit(url)
        merged = dict(parse_qsl(parts.query))
        merged.update({k: str(v) for k, v in (params or {}).items()})
        path = unquote(parts.path)
        self.calls.append((parts.netloc, path, merged))
        for (host, prefix), handler in self.routes.items():
            if parts.netloc == host and path.startswith(prefix):
                return handler(path, merged)
        raise AssertionError(f"unexpected request {url} {params}")

    def get_json(self, url, params=None, headers=None, allow_404=True):
        """Answer a GET like `citations.http.HttpClient.get_json`.

        Args:
            url: The request URL.
            params: Query parameters.
            headers: Ignored.
            allow_404: Whether a handler's None is returned rather than raised.

        Returns:
            The handler's answer.

        Raises:
            citations.http.HttpError: For a 404 when `allow_404` is False.
        """
        result = self._route(url, params)
        if result is None and not allow_404:
            raise HttpError(f"GET {url}: HTTP 404")
        return result

    def post_json(self, url, data=None, headers=None):
        """Answer a POST like `citations.http.HttpClient.post_json`.

        Args:
            url: The request URL.
            data: The form data, passed to the handler as its params.
            headers: Ignored.

        Returns:
            The handler's answer.
        """
        return self._route(url, data)

    def map(self, fn, items):
        """Run `fn` on each item in turn, like `citations.http.HttpClient.map` with one worker.

        Args:
            fn: Called with one item.
            items: The items.

        Yields:
            ``(item, result, error)``.
        """
        for item in items:
            try:
                yield item, fn(item), None
            except Exception as error:  # noqa: BLE001
                yield item, None, error


@pytest.fixture
def settings(tmp_path):
    """Settings for a throwaway store and results folder under ``tmp_path``.

    One worker, no contact email, and a dummy Overton key so Overton runs.
    """
    return Settings(db_path=tmp_path / "citations.sqlite", results_dir=tmp_path / "Results", workers=1,
                    mailto=None, overton_api_key="test-key")


@pytest.fixture
def con(settings):
    """An open connection to the test store, closed after the test."""
    connection = db.connect(settings.db_path)
    yield connection
    connection.close()


def make_ctx(con, client, settings):
    """A harvest context for the test store and a fake client.

    Args:
        con: The store connection.
        client: A `FakeClient`.
        settings: The test settings.

    Returns:
        A `citations.harvest.Context`.
    """
    return Context(con=con, client=client, settings=settings)
