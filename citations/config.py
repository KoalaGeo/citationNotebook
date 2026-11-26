"""Settings, constants and the data-centre mapping."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

CODE_VERSION = __version__
NERC_PREFIX = "10.5285/"

# Sources the pipeline harvests. A required source must have a successful,
# recent harvest or publishing is refused; an optional one only warns.
REQUIRED_SOURCES = ("datacite", "scholexplorer")
OPTIONAL_SOURCES = ("overton", "crossref")
ALL_SOURCES = REQUIRED_SOURCES + OPTIONAL_SOURCES

CENTRE_NAMES = {
    "BODC": "British Oceanographic Data Centre (BODC)",
    "CEDA": "Centre for Environmental Data Analysis (CEDA)",
    "EIDC": "Environmental Information Data Centre (EIDC)",
    "NGDC": "National Geoscience Data Centre (NGDC)",
    "PDC": "Polar Data Centre (PDC)",
}
UNKNOWN_CENTRE_NAME = "Unknown data centre"


def data_centre(publisher: str | None) -> str | None:
    """EDS data-centre code for a DataCite publisher name.

    Uses the same keyword rules as the v3 pipeline
    (``getNERCDataDOIs.process_publisher``), but returns a short code instead of
    the long name. `CENTRE_NAMES` maps a code back to its long name.

    Args:
        publisher: The ``publisher`` of a DataCite record, for example
            ``"NERC EDS Centre for Environmental Data Analysis"``.

    Returns:
        ``"BODC"``, ``"CEDA"``, ``"EIDC"``, ``"NGDC"`` or ``"PDC"``, or None when
        the publisher is empty or matches no rule.
    """
    if not isinstance(publisher, str) or not publisher.strip():
        return None
    p = publisher.lower()
    if "polar" in p:
        return "PDC"
    if "atmospheric" in p or "badc" in p or "earth" in p:
        return "CEDA"
    if "oceanographic" in p:
        return "BODC"
    if "geological" in p or "geoscience" in p:
        return "NGDC"
    if "environmental information" in p:
        return "EIDC"
    if "environmental data" in p:
        return "CEDA"
    return None


@dataclass
class Settings:
    """Every setting a pipeline run uses, with the defaults the weekly workflow runs on.

    The command line (`citations.cli`) builds one of these from its options;
    tests build their own with a temporary ``db_path`` and ``results_dir``.

    Attributes:
        db_path: The SQLite store that holds every stage's intermediate data.
        results_dir: Where ``v4/`` and ``v3/`` results are written.
        client_id: The DataCite client whose datasets are inventoried.
        mailto: Contact email sent with requests, which earns the Crossref and
            DataCite "polite" rate limits. Read from ``CITATIONS_MAILTO``.
        overton_api_key: Overton API key, read from ``OVERTON_API_KEY``. Without
            it the Overton harvest is skipped.
        workers: Worker threads each source uses for its requests.
        max_source_age_days: A source's last good harvest older than this is
            stale; publishing is refused for a stale required source.
        max_row_drop: Share of links a harvest may lose against the last good
            harvest (or the last published results) before it is rejected.
        max_error_rate: Share of failed requests that makes a harvest partial.
        reconcile_threshold: Share of DataCite-cited datasets allowed to have
            fewer harvested DataCite links than their ``citationCount``.
        accept_drop: Sources whose drop in links is accepted this run
            (``--accept-drop``).
        predates_tolerance_years: A work published this many years or more
            before the dataset it uses is excluded as ``predates-data``.
        resume_window_days: An unfinished harvest younger than this is resumed
            rather than restarted.
        works_refresh_days: Citing-work metadata older than this is fetched again.
        min_citation_success_rate: Share of DOI lookups that must return a
            formatted citation (once at least 20 are tried); below it the
            formatter is taken to be broken and the works stage fails rather
            than writing degraded citations.
        write_v3: Whether publishing also writes the v3-compatible results.
    """

    db_path: Path = Path("data/citations.sqlite")
    results_dir: Path = Path("Results")
    client_id: str = "bl.nerc"
    mailto: str | None = field(default_factory=lambda: os.environ.get("CITATIONS_MAILTO") or None)
    overton_api_key: str | None = field(default_factory=lambda: os.environ.get("OVERTON_API_KEY") or None)
    workers: int = 4
    # Publishing guards
    max_source_age_days: float = 8
    max_row_drop: float = 0.20          # a harvest losing more than this share of rows is rejected
    max_error_rate: float = 0.02        # share of failed per-DOI requests that makes a harvest partial
    reconcile_threshold: float = 0.05   # share of DataCite-cited datasets allowed to be incomplete
    # Sources whose drop in links is accepted this run (--accept-drop), for when the
    # drop is real: the harvest is not rejected and publishing is not blocked for it.
    accept_drop: frozenset = frozenset()
    # Classification
    predates_tolerance_years: int = 2   # exclude a work published this many years or more before the dataset
    # Caching / resume
    # An unfinished (interrupted or partial) harvest younger than this is resumed, not
    # restarted. Longer than the weekly schedule, so the next Sunday run picks it up.
    resume_window_days: float = 8
    works_refresh_days: float = 90      # re-fetch citing-work metadata after this long
    min_citation_success_rate: float = 0.5
    write_v3: bool = True

    @property
    def v4_dir(self) -> Path:
        """The directory the v4 results are written to: ``<results_dir>/v4``."""
        return self.results_dir / "v4"

    @property
    def v3_dir(self) -> Path:
        """The directory the v3-compatible results are written to: ``<results_dir>/v3``."""
        return self.results_dir / "v3"
