"""Identifier normalisation, so the same work from two sources merges into one link."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from .config import NERC_PREFIX

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s?#]+", re.IGNORECASE)

# Values the old harvesters wrote into empty fields; never identifiers.
PLACEHOLDERS = {
    "", "not a doi", "info not given", "unknown repository", "unknown",
    "nan", "none", "null", "n/a", "error occurred", "api request failed",
}

_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_cid$|mc_eid$)", re.IGNORECASE)


def _text(value) -> str:
    """A field's value as stripped text, with empty and placeholder values as "".

    Args:
        value: Any value read from a source: None, NaN, a number or a string.

    Returns:
        The stripped text, or ``""`` for None, NaN or one of
        `PLACEHOLDERS` (``"Info not given"``, ``"n/a"`` ...).
    """
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    text = str(value).strip()
    return "" if text.lower() in PLACEHOLDERS else text


def extract_doi(value, exclude: str | None = None) -> str | None:
    """The DOI in a value, with its original case.

    Handles bare DOIs, ``doi:`` and ``doi.org`` forms, publisher URLs with a DOI
    in the path (``https://pubs.acs.org/doi/10.1021/...``) and the doubled prefix
    some DataCite relations carry (``"10.1016/10.1111/jbi.13501"`` gives
    ``"10.1111/jbi.13501"``). Query strings and trailing punctuation are ignored.

    Args:
        value: Text that may hold a DOI.
        exclude: A DOI to ignore. A citing work's URL that mentions the cited
            dataset is not that dataset, so the dataset's DOI is passed here.

    Returns:
        The DOI, or None if there is none or it equals `exclude`.
    """
    text = _text(value)
    if not text:
        return None
    if re.match(r"https?://", text, re.IGNORECASE):
        text = urlsplit(text).path
    text = unquote(text)
    matches = DOI_RE.findall(text)
    if not matches:
        return None
    doi = matches[0]
    inner = DOI_RE.findall(doi[3:])
    if inner and doi.split("/", 1)[1].startswith("10."):
        doi = inner[-1]
    # Trailing punctuation from surrounding text; ")" only when unbalanced.
    while True:
        stripped = doi.rstrip(".,;")
        if stripped.endswith(")") and stripped.count(")") > stripped.count("("):
            stripped = stripped[:-1]
        if stripped == doi:
            break
        doi = stripped
    if exclude and doi.lower() == str(exclude).strip().lower():
        return None
    return doi


def normalise_doi(value, exclude: str | None = None) -> str | None:
    """The DOI in a value, lower case. DOIs are case-insensitive.

    Args:
        value: Text that may hold a DOI.
        exclude: A DOI to ignore, as in `extract_doi`.

    Returns:
        The bare lower-case DOI, or None.
    """
    doi = extract_doi(value, exclude)
    return doi.lower() if doi else None


def canonical_url(value) -> str | None:
    """A URL in one canonical form, so two spellings of it compare equal.

    The scheme becomes ``https``; the host is lower case without ``www.``; the
    fragment, tracking parameters (``utm_*``, ``fbclid`` ...) and any trailing
    slash are removed.

    Args:
        value: Text that may be a URL.

    Returns:
        The canonical URL, or None if `value` is not an ``http(s)`` URL.
    """
    text = _text(value)
    if not re.match(r"https?://", text, re.IGNORECASE):
        return None
    parts = urlsplit(text)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)])
    path = parts.path.rstrip("/") if parts.path not in ("", "/") else ""
    return urlunsplit(("https", host, path, query, ""))


def normalise_id(value, scheme: str | None = None, exclude: str | None = None) -> tuple[str, str] | None:
    """The identifier and identifier type of a citing work.

    A DOI anywhere in a URL path wins, so ``https://doi.org/10.1/x`` and
    ``10.1/X`` become the same identifier. PubMed, PubMed Central and Handle
    identifiers are given a prefix (``pmid:``, ``pmc:``, ``hdl:``); anything else
    that is a URL is canonicalised with `canonical_url`.

    Args:
        value: The identifier as the source gave it.
        scheme: The source's own hint about the identifier, such as the Scholix
            ``IDScheme`` (``doi``, ``pmid``, ``pmc``, ``handle``, ``url``).
        exclude: The cited dataset's DOI; a value that resolves to it is not a
            citing work.

    Returns:
        ``(identifier, type)`` with type one of ``doi``, ``pmid``, ``pmc``,
        ``handle`` or ``url``; or None when there is no usable identifier.
    """
    text = _text(value)
    if not text:
        return None
    scheme = (scheme or "").lower()
    if scheme in ("pmid", "pmc", "handle", "hdl"):
        kind = "handle" if scheme in ("handle", "hdl") else scheme
        bare = re.sub(r"^(pmid|pmc|hdl|handle):\s*", "", text, flags=re.IGNORECASE)
        bare = re.sub(r"^https?://(hdl\.handle\.net|identifiers\.org/[a-z]+)/", "", bare, flags=re.IGNORECASE)
        if kind == "pmc" and not bare.upper().startswith("PMC"):
            bare = "PMC" + bare
        return (f"{'hdl' if kind == 'handle' else kind}:{bare.strip()}", kind)
    doi = normalise_doi(text)
    if doi:
        if exclude and doi == str(exclude).strip().lower():
            return None  # the dataset itself, however it is written
        return (doi, "doi")
    url = canonical_url(text)
    if url:
        return (url, "url")
    return None


def link_id(data_doi: str, citing_id: str) -> str:
    """A stable id for one dataset and citing-work pair.

    Args:
        data_doi: The dataset's lower-case DOI.
        citing_id: The citing work's normalised identifier.

    Returns:
        The SHA-1 hex digest of ``"<data_doi>|<citing_id>"``. The same pair gets
        the same id in every run.
    """
    return hashlib.sha1(f"{data_doi}|{citing_id}".encode("utf-8")).hexdigest()


def is_nerc_dataset(citing_id: str | None) -> bool:
    """Whether a citing work is itself a NERC EDS dataset.

    Args:
        citing_id: A normalised identifier.

    Returns:
        True when it is a DOI under the NERC prefix (``10.5285/``).
    """
    return bool(citing_id) and citing_id.startswith(NERC_PREFIX)


def doi_url(doi: str) -> str:
    """The ``https://doi.org/`` link for a DOI.

    Args:
        doi: A bare DOI.

    Returns:
        The resolver URL.
    """
    return f"https://doi.org/{doi}"


def work_url(citing_id: str, citing_id_type: str | None) -> str:
    """A resolvable link for a citing work's identifier.

    Args:
        citing_id: A normalised identifier, as from `normalise_id`.
        citing_id_type: Its type: ``doi``, ``pmid``, ``pmc``, ``handle`` or
            ``url``.

    Returns:
        A ``doi.org``, PubMed, PubMed Central or Handle link; a URL is returned
        as it is.
    """
    if citing_id_type == "doi":
        return doi_url(citing_id)
    bare = citing_id.split(":", 1)[1] if citing_id_type in ("pmid", "pmc", "handle") and ":" in citing_id else citing_id
    if citing_id_type == "pmid":
        return f"https://pubmed.ncbi.nlm.nih.gov/{bare}/"
    if citing_id_type == "pmc":
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{bare}/"
    if citing_id_type == "handle":
        return f"https://hdl.handle.net/{bare}"
    return citing_id   # a URL already
