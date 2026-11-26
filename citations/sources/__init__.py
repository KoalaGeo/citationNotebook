"""Link sources: one module per API the pipeline harvests.

Each module exposes:

- ``SOURCE``: its name, as used on the command line and in the store;
- ``BUCKETS``: the rate-limit buckets it calls
  (`citations.http.bucket_for`), for counting 429 responses;
- ``harvest(ctx, run_id)``: fetches its links into the store and returns
  ``{"details": {...}}``, counts that are recorded with the run.

`citations.harvest` runs a module's ``harvest`` and decides the run's
status. `MODULES` maps each ``SOURCE`` to its module.
"""

from . import crossref, datacite, overton, scholexplorer

MODULES = {
    datacite.SOURCE: datacite,
    scholexplorer.SOURCE: scholexplorer,
    overton.SOURCE: overton,
    crossref.SOURCE: crossref,
}
