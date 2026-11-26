"""Citation strings for the works that cite NERC datasets.

Ported from citations_fun/getCitationString.py (v3) with its behaviour kept:
every string is plain text (no HTML entities, inline markup or line breaks);
a formatted citation comes from DOI content negotiation only for real DOIs and
only when the response is a real citation; otherwise a citation is built from
the work's own metadata, never a placeholder or an error message. If most
lookups fail the run raises, so a broken formatter fails visibly instead of
writing error messages into the results (as happened from late Feb 2026).

What changed for v4: it works on plain dicts (no pandas), and strings are
cached per work in the SQLite store, so each DOI is formatted once.
"""

import ast
import html
import html.entities
import re
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .ids import extract_doi

log = logging.getLogger(__name__)

# DOI content negotiation: doi.org redirects to the registration agency
# (Crossref, DataCite, ...) which formats the citation with citeproc.
# https://citation.crosscite.org/docs.html
CONTENT_NEGOTIATION_URL = "https://doi.org/{doi}"

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s?#]+", re.IGNORECASE)

# Bodies the formatters return with errors (sometimes with HTTP 200).
# Kept specific: a broad "not found" could match a genuine title.
FORMATTER_ERRORS = re.compile(
    r"^unknown style|^doi not found|metadata could not be retrieved|"
    r"^resource not found|^too many requests|^service unavailable|"
    r"^internal server error|<html|<!doctype|"
    # Content negotiation reports errors as JSON, e.g.
    # {"code":"style-not-found","message":"Style [...] does not exist",...}
    r"^\s*[{\[]|style-not-found",
    re.IGNORECASE,
)

# Placeholders the harvesting steps write into empty fields.
PLACEHOLDERS = {
    "", "not a doi", "info not given", "unknown repository", "unknown",
    "nan", "none", "null", "n/a", "error occurred",
}


# Inline formatting the formatters and publisher metadata put into text:
# DataCite's formatter italicises titles (<i>...</i>, &amp;), Crossref titles
# carry JATS markup (<i>, <scp>, <sub>, <sup>, mml:*) and stray line breaks.
# Only these tags are removed, so a title like "<S1-11> Effect of ..." survives.
_INLINE_TAG = re.compile(
    r"</?\s*(?:i|b|u|em|strong|sc|scp|span|sup|sub|small|"
    r"(?:mml|jats|ns\d*):[\w.-]+|math)\b[^>]*/?>",
    re.IGNORECASE,
)
_BREAK_TAG = re.compile(r"</?\s*(?:br|p)\b[^>]*/?>", re.IGNORECASE)
# <sub>/<sup> with the whitespace around them and the next character, so the
# replacement can decide which side the script attaches to.
_SUP_SUB = re.compile(r"(\s*)<\s*(sup|sub)\b[^>]*>(.*?)<\s*/\s*\2\s*>(\s*)(?=(.?))",
                      re.IGNORECASE | re.DOTALL)
_SUP_CHARS, _SUB_CHARS = "0123456789+-−=()n", "0123456789+-−=()"
_SUP_MAP = str.maketrans(_SUP_CHARS, "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ⁿ")
_SUB_MAP = str.maketrans(_SUB_CHARS, "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎")


def _script(match):
    """Replace one ``<sup>`` or ``<sub>`` element with plain text.

    Uses Unicode superscript or subscript characters where they exist (N₂O,
    ¹³⁷Cs, m²), else the plain characters, and decides which side the script
    attaches to.

    Args:
        match: A match of `_SUP_SUB`.

    Returns:
        The replacement text.
    """
    before, kind, inner, after, following = match.groups()
    kind, inner = kind.lower(), re.sub(r"\s+", "", inner)
    table, allowed = (_SUP_MAP, _SUP_CHARS) if kind == "sup" else (_SUB_MAP, _SUB_CHARS)
    # Unicode sub/superscript where one exists (N₂O, ¹³⁷Cs, m²); otherwise plain text.
    out = inner.translate(table) if inner and all(c in allowed for c in inner) else inner
    if kind == "sup" and following[:1].isupper():
        # Isotope before an element symbol: "using <sup>137</sup>Cs" -> "using ¹³⁷Cs".
        return f"{before}{out}"
    # Otherwise the script belongs to what precedes it ("N <sub>2</sub> O" ->
    # "N₂O", "m <sup>2</sup>" -> "m²"); keep a following space only before a
    # new word, not before the rest of a formula.
    joins_formula = following[:1].isupper() or following[:1].isdigit() or following[:1] == "("
    return out + ("" if joins_formula or not after else " ")


def _fix_entity_case(match):
    """Undo title-casing of an HTML entity name without touching real capitals.

    Title-casing turns ``&amp;`` into ``&Amp;`` (not an entity, so
    `html.unescape` leaves it alone) and ``caf&eacute;`` into
    ``caf&Eacute;`` (a valid entity, but the wrong letter). The name is lowered
    when it isn't a valid entity, or when it sits mid-word after a lowercase
    letter; ``&Aacute;lvarez`` and ``&Ouml;sterreich`` keep their capitals.

    Args:
        match: A match of ``&name;``.

    Returns:
        The entity, with its name lowered where needed.
    """
    name = match.group(1)
    previous = match.string[match.start() - 1:match.start()]
    if (name + ";") not in html.entities.html5 or previous.islower():
        return f"&{name.lower()};"
    return match.group(0)


def _missing(value):
    """Whether a value is missing: None or NaN.

    Args:
        value: Any value.

    Returns:
        True for None or a float NaN.
    """
    return value is None or (isinstance(value, float) and value != value)


def plain_text(value):
    """A citation or title as clean plain text.

    HTML entities are decoded (twice, for double-escaped text), inline markup
    (``<i>``, ``<scp>``, MathML ...) is removed, ``<sub>`` and ``<sup>`` become
    Unicode where possible, and whitespace, line breaks included, collapses to
    single spaces.

    Args:
        value: The text, or None or NaN.

    Returns:
        The plain text; ``""`` for a missing value.
    """
    if _missing(value):
        return ""
    text = str(value)
    for _ in range(2):  # also undo double escaping such as &amp;amp;
        # Crossref title-casing produces "&Amp;": entity names are case-sensitive.
        decoded = html.unescape(re.sub(r"&([A-Za-z]+);", _fix_entity_case, text))
        if decoded == text:
            break
        text = decoded
    text = _BREAK_TAG.sub(" ", text)
    text = _SUP_SUB.sub(_script, text)
    text = _INLINE_TAG.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r" ([.,;:)\]])", r"\1", text).replace("( ", "(").replace("[ ", "[")


def _clean(value):
    """A value as stripped text, or ``""`` for missing values and harvester placeholders.

    Args:
        value: Any value.

    Returns:
        The text, or ``""``.
    """
    if _missing(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in PLACEHOLDERS else text


def normalise_doi(value, data_doi=None):
    """The DOI in a value, with its original case.

    Args:
        value: Text that may hold a DOI.
        data_doi: The cited dataset's DOI, which is never returned.

    Returns:
        The DOI, or None when there is none or it is `data_doi`.
    """
    return extract_doi(value, exclude=data_doi)


def is_real_citation(text):
    """Whether a string is a usable citation rather than an error or a placeholder.

    Args:
        text: A citation string as a formatter returned it, or None.

    Returns:
        True when it is at least 20 characters and matches none of the
        formatter error messages in `FORMATTER_ERRORS`.
    """
    cleaned = _clean(text)
    return bool(cleaned) and len(cleaned) >= 20 and not FORMATTER_ERRORS.search(cleaned)


def _authors(value, limit=3):
    """Authors as a short citation list from the varied author formats.

    Args:
        value: A list of ``[given, family]`` pairs or names, or its Python
            literal text, as v3 wrote it.
        limit: How many authors to name before ``et al.``.

    Returns:
        For example ``"Smith J.A., Jones B., Natural History Museum, et al."``;
        the text itself when it is not a list; ``""`` when empty.
    """
    text = _clean(value)
    if not text:
        return ""
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text
    names = []
    for item in parsed if isinstance(parsed, (list, tuple)) else [parsed]:
        if isinstance(item, (list, tuple)):
            parts = [_clean(p) for p in item if _clean(p)]
            if len(parts) >= 2:   # [given, family]
                given, family = parts[0], parts[-1]
                initials = "".join(f"{p[0]}." for p in re.split(r"[\s.\-]+", given) if p)
                names.append(f"{family} {initials}".strip())
            elif parts:           # [organisation]
                names.append(parts[0])
        elif _clean(item):
            names.append(_clean(item))
    if not names:
        return ""
    shown = ", ".join(names[:limit])
    return f"{shown}, et al." if len(names) > limit else shown


def _year(row):
    """A row's publication year.

    Args:
        row: A citation row.

    Returns:
        The four-digit year from ``publicationYear``, else the first plausible
        year in ``pub_date``, else ``""``.
    """
    year = _clean(row.get("publicationYear"))
    if re.fullmatch(r"\d{4}(\.0)?", year):
        return year[:4]
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", _clean(row.get("pub_date")))
    return match.group(1) if match else ""


def fallback_citation(row, doi=None):
    """A plain citation built from a row's metadata.

    The form is ``Authors (Year). Title. Publisher. https://doi.org/DOI``, with
    missing parts left out and a publisher that repeats the title or an
    organisational author skipped.

    Args:
        row: A citation row (``pub_authors``, ``publicationYear``, ``pub_date``,
            ``pub_title``, ``pub_publisher``).
        doi: The work's DOI, if it has one.

    Returns:
        The citation, or ``""`` when there is no title: without one the string
        isn't worth showing.
    """
    authors = _authors(row.get("pub_authors"))
    year = _year(row)
    title = _clean(row.get("pub_title")).rstrip(".")
    publisher = _clean(row.get("pub_publisher")).rstrip(".")

    parts = []
    if authors:
        parts.append(f"{authors} ({year})." if year else f"{authors}.")
    elif year:
        parts.append(f"({year}).")
    if title:
        parts.append(f"{title}.")
    # Skip a publisher that repeats the title or an organisational author.
    if publisher and publisher.lower() not in title.lower() and publisher.lower() != authors.lower():
        parts.append(f"{publisher}.")
    if doi:
        parts.append(f"https://doi.org/{doi}")
    # Without a title the string isn't worth showing; the widget falls back
    # to the URL itself.
    return " ".join(parts) if title else ""


def _session():
    """A `requests.Session` with retries, for when no rate limiter is given.

    Returns:
        The session.
    """
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,  # return the last response; status is checked below
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_formatted(session, doi, style, locale, timeout=15, observe=None):
    """A formatted citation for a DOI, by DOI content negotiation.

    Args:
        session: The session to request with.
        doi: The DOI.
        style: A CSL style name, such as ``"apa"``.
        locale: A CSL locale, such as ``"en-GB"``.
        timeout: The request timeout in seconds.
        observe: Called with every response, if given (the caller counts 429s
            with it).

    Returns:
        The citation, or None if the request failed or the formatter gave no
        real citation.
    """
    try:
        response = session.get(
            CONTENT_NEGOTIATION_URL.format(doi=doi),
            headers={
                "Accept": f"text/x-bibliography; style={style}; locale={locale}",
                "Accept-Charset": "utf-8",
            },
            timeout=timeout,
        )
    except requests.RequestException as error:
        log.debug("%s: request failed (%s)", doi, error)
        return None
    if observe:
        observe(response)
    response.encoding = "utf-8"
    text = response.text.strip()
    if response.status_code != 200 or not is_real_citation(text):
        log.debug("%s: no citation (HTTP %s: %r)", doi, response.status_code, text[:80])
        return None
    return text


def format_citations(
    rows,
    reuse=None,
    style="apa",
    locale="en-GB",
    min_success_rate=0.5,
    pause=0.1,
    session=None,
    workers=1,
    limiter=None,
):
    """A plain-text citation string for each row.

    Each DOI not in `reuse` is looked up once, `workers` at a time. A row with
    no DOI, or whose lookup failed, gets `fallback_citation`.

    Args:
        rows: Dicts with ``data_doi``, ``pub_doi``, ``pub_title``,
            ``pub_authors``, ``publicationYear``, ``pub_date`` and
            ``pub_publisher``, and optionally ``bucket`` (the rate-limit bucket
            for `limiter`).
        reuse: ``{doi: citation}``; real citations in it are used instead of
            being fetched again.
        style: The CSL style.
        locale: The CSL locale.
        min_success_rate: If fewer than this share of the DOIs looked up get a
            formatted citation (and at least 20 were tried), raise instead of
            returning degraded strings. None disables the check.
        pause: Seconds to wait after each lookup when there is no `limiter`.
        session: A session to use for every lookup; one per thread when None.
        workers: DOIs fetched at once.
        limiter: Something like `citations.http.HttpClient`, with
            ``limited(bucket)`` (a context manager that waits for a turn in that
            rate limit and is held while the request runs) and
            ``observe(bucket, response)`` (which counts 429s).

    Returns:
        ``(strings, sources, stats)``. `sources` says for each row whether its
        string was ``"reused"``, ``"formatter"`` or ``"fallback"`` (``""`` when
        there is none). `stats` counts ``formatted``, ``reused``, ``fallback``,
        ``empty``, ``tried`` and ``succeeded``.

    Raises:
        RuntimeError: If too few lookups succeeded (see `min_success_rate`).
    """
    reuse = {k.lower(): v for k, v in (reuse or {}).items() if is_real_citation(v)}
    stats = {"formatted": 0, "reused": 0, "fallback": 0, "empty": 0, "tried": 0, "succeeded": 0}
    strings, sources = [], []

    # Each DOI that isn't reused is looked up once, `workers` at a time.
    todo = {}
    for row in rows:
        doi = normalise_doi(row.get("pub_doi"), row.get("data_doi"))
        if doi and doi.lower() not in reuse:
            todo.setdefault(doi.lower(), (doi, row.get("bucket")))
    local = threading.local()

    def lookup(item):
        """Fetch one DOI's formatted citation within the rate limit.

        Args:
            item: ``(doi, bucket)``.

        Returns:
            The citation, or None.
        """
        doi, bucket = item
        own = session or getattr(local, "session", None)
        if own is None:
            own = local.session = _session()
        with (limiter.limited(bucket) if limiter else nullcontext()):
            text = fetch_formatted(own, doi, style, locale,
                                   observe=(lambda r: limiter.observe(bucket, r)) if limiter else None)
        if pause and not limiter:
            time.sleep(pause)
        return text

    if workers > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="citations") as pool:
            fetched = dict(zip(todo, pool.map(lookup, todo.values())))
    else:
        fetched = {key: lookup(item) for key, item in todo.items()}
    stats["tried"] = len(fetched)
    stats["succeeded"] = sum(text is not None for text in fetched.values())

    for row in rows:
        doi = normalise_doi(row.get("pub_doi"), row.get("data_doi"))
        text, origin = None, ""
        if doi:
            key = doi.lower()
            if key in reuse:
                text, origin = reuse[key], "reused"
                stats["reused"] += 1
            else:
                text = fetched[key]
                if text is not None:
                    origin = "formatter"
                    stats["formatted"] += 1
        if not text:
            text = fallback_citation(row, doi)
            origin = "fallback" if text else ""
            stats["fallback" if text else "empty"] += 1
        strings.append(plain_text(text))
        sources.append(origin)

    if min_success_rate is not None and stats["tried"] >= 20:
        rate = stats["succeeded"] / stats["tried"]
        if rate < min_success_rate:
            message = (
                f"Only {stats['succeeded']} of {stats['tried']} DOIs ({rate:.0%}) got a formatted "
                f"citation from {CONTENT_NEGOTIATION_URL} with style={style}. The formatter is "
                "probably failing; not writing results."
            )
            raise RuntimeError(message)

    return strings, sources, stats
