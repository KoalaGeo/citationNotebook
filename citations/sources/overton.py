"""Overton: policy documents citing NERC datasets.

Ported from getOvertonCitations.py. Deliberately sequential with >=1s between
requests -- Overton is a keyed commercial API and the old pipeline already
respected a 1 req/s pace; parallelising this source would be impolite.

The API key comes from the OVERTON_API_KEY environment variable. The key that
was previously hard-coded in the repo is kept as a fallback so nothing breaks,
but it should be moved to a repository secret and rotated.
"""

import os
import time

from ..http import get_json

OVERTON_URL = "https://app.overton.io/documents.php"
_LEGACY_KEY = "3c7b1a-849d90-77f9da"  # pre-existing public-in-repo key; rotate + move to a secret


def api_key():
    key = os.environ.get("OVERTON_API_KEY")
    if key:
        return key
    print("[overton] OVERTON_API_KEY not set; falling back to the legacy "
          "in-repo key. Move the key to a repository secret.")
    return _LEGACY_KEY


def parse_document(doc, queried_doi):
    """One Overton result -> a citation row."""
    highlights = doc.get("highlights") or []
    first = highlights[0] if highlights and isinstance(highlights[0], dict) else {}
    source = doc.get("source") or {}
    return {
        "data_doi": first.get("doi") or queried_doi,
        "pub_doi": doc.get("document_url") or "",   # usually a plain URL, not a DOI
        "source_id": "overton",
        "relation_type": first.get("type"),
        "pub_title": doc.get("title"),
        "pub_date": doc.get("published_on"),
        "pub_authors": doc.get("authors") or [],
        "pub_type": doc.get("overton_policy_document_series"),
        "pub_publisher": source.get("title") if isinstance(source, dict) else None,
    }


def fetch_citations(session, data_dois, delay=1.05):
    rows, errors = [], 0
    key = api_key()
    for doi in data_dois:
        started = time.time()
        payload, err = get_json(session, OVERTON_URL,
                                params={"plain_dois_cited": doi,
                                        "format": "json", "api_key": key})
        if err:
            print(f"[overton] {doi}: {err}")
            errors += 1
        else:
            for doc in payload.get("results") or []:
                row = parse_document(doc, doi)
                if row["pub_doi"]:
                    rows.append(row)
        elapsed = time.time() - started
        if elapsed < delay:                    # enforce >=~1s between requests
            time.sleep(delay - elapsed)
    return rows, errors
