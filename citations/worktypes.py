"""One vocabulary for work types: Crossref's (https://api.crossref.org/types).

Each source names types its own way: Crossref ``journal-article``, DataCite a
``resourceTypeGeneral`` (``JournalArticle``) and a CSL type (``article-journal``),
Scholexplorer ``publication``, Overton its document series (``Working paper``).
Mixed, the same kind of work was split across several values. Everything is
mapped to Crossref's vocabulary here: it covers most citing works already and is
what v3's ``publication_type`` has always carried. ``other`` when no Crossref
type fits, None when nothing is known about the work.
"""

from __future__ import annotations

import re

CROSSREF_TYPES = frozenset({
    "book", "book-chapter", "book-part", "book-section", "book-series", "book-set", "book-track",
    "component", "database", "dataset", "dissertation", "edited-book", "grant", "journal",
    "journal-article", "journal-issue", "journal-volume", "monograph", "other", "peer-review",
    "posted-content", "proceedings", "proceedings-article", "proceedings-series", "reference-book",
    "reference-entry", "report", "report-component", "report-series", "standard",
})

# Names compared lower case with anything but letters removed, so DataCite's JournalArticle,
# BookChapter or PeerReview already match a Crossref type. These are the other names; any
# name not matched (Scholexplorer's "publication", DataCite's Software or Image ...) is "other".
_ALIASES = {
    # DataCite resourceTypeGeneral
    "datapaper": "journal-article",
    "preprint": "posted-content",
    "conferencepaper": "proceedings-article",
    "conferenceproceeding": "proceedings",
    # CSL, as DataCite's types.citeproc gives it
    "articlejournal": "journal-article",
    "article": "posted-content",          # CSL: an article not published in a journal, i.e. a preprint
    "chapter": "book-chapter",
    "paperconference": "proceedings-article",
    "thesis": "dissertation",
    "review": "peer-review",
    "entry": "reference-entry",
    "entrydictionary": "reference-entry",
    "entryencyclopedia": "reference-entry",
}


def _key(value) -> str:
    """A type name reduced for matching: lower case, letters only.

    Args:
        value: A type name from any source.

    Returns:
        For example ``"journalarticle"`` for ``"JournalArticle"``,
        ``"journal-article"`` or ``"Journal Article"``.
    """
    return re.sub(r"[^a-z]", "", str(value).lower())


_KEYS = {_key(t): t for t in CROSSREF_TYPES}
# DataCite resourceTypeGeneral values too broad to say more than the CSL type does.
_BROAD = {"text", "other"}


def crossref_type(value, source: str | None = None) -> str | None:
    """The Crossref type for a type name from any source.

    Args:
        value: The type as the source gave it, for example ``"JournalArticle"``,
            ``"article-journal"``, ``"publication"`` or ``"Working paper"``.
        source: The source the name came from. Overton's document series are
            mapped to ``report`` (or ``journal-article`` for a scholarly article).

    Returns:
        A value from `CROSSREF_TYPES`, ``other`` when none fits, or None
        when `value` is empty.
    """
    if value is None or not str(value).strip():
        return None
    key = _key(value)
    if key in _KEYS:
        return _KEYS[key]
    if source == "overton":
        # Overton's document series: policy reports, briefs, working papers ... Crossref
        # registers that grey literature as reports; a scholarly article stays one.
        return "journal-article" if key == "scholarlyarticle" else "report"
    return _ALIASES.get(key, "other")


def datacite_type(types: dict | None) -> str | None:
    """The Crossref type for a DataCite record.

    ``resourceTypeGeneral`` is used first; when it is too broad (``Text`` or
    ``Other``) the CSL type in ``citeproc`` is used instead.

    Args:
        types: The record's ``attributes.types`` object, or None.

    Returns:
        A Crossref type, or None when the record gives no type.
    """
    types = types or {}
    general = types.get("resourceTypeGeneral")
    if general and _key(general) not in _BROAD:
        return crossref_type(general)
    return crossref_type(types.get("citeproc")) or crossref_type(general)
