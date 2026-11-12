"""End-to-end runs against a fake DataCite / Scholexplorer / Overton / Crossref world."""

import csv
import json

import pytest

from citations import citation_text, db
from citations.harvest import run_harvest
from citations.http import HttpError
from citations.inventory import run_inventory
from citations.merge import run_merge
from citations.publish import V3_COLUMNS, run_publish
from citations.works import run_works

from conftest import FakeClient, make_ctx

A, B, C = "10.5285/aaaa-ngdc", "10.5285/bbbb-pdc", "10.5285/cccc-pdc"


def record(doi, publisher, year, citations=0, related=()):
    return {"id": doi, "type": "dois", "attributes": {
        "doi": doi, "titles": [{"title": f"Dataset {doi[-8:]}"}], "publisher": {"name": publisher},
        "publicationYear": year, "types": {"resourceTypeGeneral": "Dataset"}, "registered": f"{year}-01-01T00:00:00Z",
        "creators": [{"name": "Bloggs, Jo", "givenName": "Jo", "familyName": "Bloggs",
                      "nameIdentifiers": [{"nameIdentifier": "https://orcid.org/0000-0001", "nameIdentifierScheme": "ORCID"}]}],
        "citationCount": citations,
        "relatedIdentifiers": [{"relationType": r, "relatedIdentifierType": t, "relatedIdentifier": i} for r, t, i in related],
    }}


NGDC = "NERC EDS National Geoscience Data Centre"
PDC = "NERC EDS UK Polar Data Centre"
RECORDS = [
    record(A, NGDC, 2020, citations=2, related=[
        ("IsReferencedBy", "DOI", "10.1234/META-PAPER"),
        ("References", "DOI", "10.9999/outgoing"),          # the dataset cites it: not a link to the dataset
        ("IsDescribedBy", "URL", "https://example.org/docs/a.zip"),
    ]),
    record(B, PDC, 2021),
    record(C, PDC, 2019),
]


class World:
    """Mutable fake APIs, so a test can break one source."""

    def __init__(self):
        self.total = 3
        self.scholix_fail = set()
        self.scholix_empty = False
        self.crossref_fail = set()

    # DataCite REST
    def dois(self, path, params):
        if path == "/dois":
            if params.get("page[cursor]") == "1":
                return {"data": RECORDS[:2], "meta": {"total": self.total},
                        "links": {"next": "https://api.datacite.org/dois?client-id=bl.nerc&page%5Bcursor%5D=abc"}}
            assert params.get("affiliation") == "true"   # re-added to the cursor link
            return {"data": [RECORDS[2], RECORDS[1]], "meta": {"total": self.total}, "links": {}}  # B repeated
        doi = path[len("/dois/"):].lower()
        if doi == A:
            return {"data": {"attributes": {"citationCount": 2}, "relationships": {"citations": {"data": [
                {"id": "10.1234/ARTICLE-X", "type": "dois"}, {"id": C, "type": "dois"}]}}}}
        return None

    def events(self, path, params):
        assert params["doi"] == A
        return {"data": [
            {"attributes": {"subj-id": "https://doi.org/10.1234/article-x", "obj-id": f"https://doi.org/{A}",
                            "relation-type-id": "references", "source-id": "crossref"}},
            {"attributes": {"subj-id": f"https://doi.org/{A}", "obj-id": f"https://doi.org/{C}",
                            "relation-type-id": "is-referenced-by", "source-id": "datacite-related"}},
            {"attributes": {"subj-id": "https://api.datacite.org/reports/1", "obj-id": f"https://doi.org/{A}",
                            "relation-type-id": "total-resolutions-regular", "source-id": "datacite-resolution"}},
        ], "links": {}}

    # Scholexplorer
    def scholix(self, path, params):
        doi = params["targetPid"]
        if doi in self.scholix_fail:
            raise HttpError("HTTP 503")
        links = []
        if not self.scholix_empty:
            if doi == A:
                links = [
                    self._link("IsRelatedTo", "cites", "doi", "10.1234/article-x", "Article X"),
                    self._link("IsRelatedTo", "HasAmongTopNSimilarDocuments", "doi", C, "Dataset C"),
                    self._link("IsRelatedTo", "IsSourceOf", "doi", "10.1234/derived", "Derived"),
                ]
            elif doi == B:
                links = [self._link("IsRelatedTo", "cites", "doi", "10.1234/old-paper", "Old paper", "2015")]
        return {"totalLinks": len(links), "totalPages": 1 if links else 0, "result": links}

    @staticmethod
    def _link(name, subtype, scheme, ident, title, date="2021-03-01"):
        return {"RelationshipType": {"Name": name, "SubType": subtype},
                "source": {"Identifier": [{"ID": ident, "IDScheme": scheme}], "Title": title, "PublicationDate": date,
                           "Type": "publication", "Publisher": [{"name": "Journal"}], "Creator": [{"name": "Smith, A."}]}}

    # Overton
    def overton_set(self, path, data):
        assert A in data["dois"]
        return {"set": "set:1"}

    def overton_docs(self, path, params):
        return {"results": [{
            "title": "A policy", "published_on": "2023-01-01", "document_url": "https://gov.example/policy.pdf",
            "source": {"title": "UK Government"}, "authors": ["Department X"],
            "highlights": [{"type": "references", "doi": A}, {"type": "references", "doi": B.upper()}],
        }], "query": {"current_page": 1, "pages": 1, "next_page_url": None}}

    # Crossref
    def datacitations(self, path, params):
        items = []
        if params["object-id"] == A:
            items = [{"relation": "is_part_of", "subject": {"id": "10.1234/article-z", "type": "journal-article"},
                      "object": {"id": A}}]
        return {"status": "ok", "message": {"total-results": len(items), "next-page": None, "items": items}}

    def crossref_works(self, path, params):
        doi = path[len("/works/"):].lower()
        if doi in self.crossref_fail:
            raise HttpError("HTTP 503")
        known = {"10.1234/article-x": [2021, 5, 1], "10.1234/meta-paper": [2020], "10.1234/article-z": [2022, 2],
                 "10.1234/old-paper": [2015]}
        if doi not in known:
            return None
        return {"message": {"title": [doi.split("/")[1].title()], "type": "journal-article", "issued": {"date-parts": [known[doi]]},
                            "container-title": ["Journal X"], "publisher": "Pub", "author": [{"given": "Ann", "family": "Smith"}]}}

    def client(self):
        return FakeClient({
            ("api.datacite.org", "/dois"): self.dois,
            ("api.datacite.org", "/events"): self.events,
            ("api.scholexplorer.openaire.eu", "/v3/Links"): self.scholix,
            ("app.overton.io", "/generate_id_set.php"): self.overton_set,
            ("app.overton.io", "/documents.php"): self.overton_docs,
            ("api.crossref.org", "/beta/datacitations"): self.datacitations,
            ("api.crossref.org", "/works/"): self.crossref_works,
        })


class FakeFormatter:
    class Response:
        def __init__(self, text):
            self.status_code, self.text, self.encoding = 200, text, None

    def get(self, url, headers=None, timeout=None):
        doi = url.split("doi.org/", 1)[1]
        return self.Response(f"Smith, A. (2021). A formatted citation for {doi}. Journal X.")


@pytest.fixture(autouse=True)
def no_network_formatter(monkeypatch):
    monkeypatch.setattr(citation_text, "_session", lambda: FakeFormatter())


def run_all(con, settings, world, sources=("datacite", "scholexplorer", "overton", "crossref")):
    client = world.client()
    ctx = make_ctx(con, client, settings)
    assert run_inventory(con, client, settings.client_id) == "success"
    statuses = {s: run_harvest(ctx, s) for s in sources}
    assert run_works(con, client, settings) in ("success", "partial")
    assert run_merge(con, settings, today="2026-10-11") == "success"
    return statuses, run_publish(con, settings)


def read_csv(path, encoding="utf-8"):
    with open(path, encoding=encoding, newline="") as handle:
        return list(csv.DictReader(handle))


def test_full_run(con, settings):
    statuses, published = run_all(con, settings, World())
    assert set(statuses.values()) == {"success"}
    assert published == "success"

    links = {(r["data_doi"], r["citing_id"]): r for r in read_csv(settings.v4_dir / "links.csv")}
    x = links[(A, "10.1234/article-x")]
    assert x["relation_class"] == "citation" and x["counted"] == "true"
    assert json.loads(x["sources"]) == ["datacite:crossref", "scholexplorer"]   # one link, both sources
    # DataCite says C references A, Scholexplorer says they are similar: citation wins, then it is a dataset link.
    assert links[(A, C)]["relation_class"] == "dataset-link" and links[(A, C)]["counted"] == "false"
    assert links[(A, "10.1234/meta-paper")]["sources"] == '["datacite:metadata"]'
    assert links[(A, "https://example.org/docs/a.zip")]["relation_class"] == "documentation"
    assert links[(A, "10.1234/article-z")]["relation_class"] == "supplement"
    old = links[(B, "10.1234/old-paper")]
    assert old["status"] == "excluded" and old["exclusion_reason"] == "predates-data"
    assert (A, "10.9999/outgoing") not in links and (A, "10.1234/derived") not in links
    assert {k for k in links if k[1] == "https://gov.example/policy.pdf"} == {(A, "https://gov.example/policy.pdf"),
                                                                              (B, "https://gov.example/policy.pdf")}

    datasets = {r["doi"]: r for r in read_csv(settings.v4_dir / "datasets.csv")}
    assert len(datasets) == 3                       # the repeated record of B is dropped
    assert datasets[A]["data_centre"] == "NGDC" and datasets[A]["counted_citations"] == "4"
    assert datasets[A]["first_cited"] == "2020"
    assert datasets[B]["excluded_links"] == "1"

    works = {r["citing_id"]: r for r in read_csv(settings.v4_dir / "works.csv")}
    assert works["10.1234/article-x"]["issued"] == "2021-05-01" and works["10.1234/article-x"]["issued_precision"] == "day"
    assert works[C]["metadata_source"] == "inventory"
    assert works["https://gov.example/policy.pdf"]["title"] == "A policy"
    # One vocabulary: Crossref's. Overton policy documents are reports.
    assert works["10.1234/article-x"]["work_type"] == "journal-article"
    assert works["https://gov.example/policy.pdf"]["work_type"] == "report"
    assert works[C]["work_type"] == "dataset"
    # A web page with no metadata gets its link as the citation, not an empty one.
    docs = works["https://example.org/docs/a.zip"]
    assert docs["title"] == "" and docs["citation_text"] == "https://example.org/docs/a.zip"
    assert all(w["citation_text"] for w in works.values())
    assert all("Info not given" not in json.dumps(w) for w in works.values())

    manifest = json.loads((settings.v4_dir / "manifest.json").read_text())
    assert manifest["counts"]["counted_links"] == 5
    assert manifest["reconciliation"]["incomplete_datasets"] == 0
    assert manifest["guards"]["problems"] == []
    # Readers fetch the files one by one; the hashes let them check they got one consistent set.
    import hashlib
    assert set(manifest["files"]) == {"datasets.csv", "datasets.json", "links.csv", "links.jsonl", "works.csv",
                                      "works.json", "reconciliation.csv"}
    for name, info in manifest["files"].items():
        data = (settings.v4_dir / name).read_bytes()
        assert info == {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    # v3 compatibility: the same 18 columns, counted links only, JSON grouped by data centre.
    v3 = read_csv(settings.v3_dir / "latest_results.csv", encoding="utf-8-sig")
    assert list(v3[0].keys()) == V3_COLUMNS and len(v3) == 5
    assert {r["data_publisher"] for r in v3} == {"National Geoscience Data Centre (NGDC)", "Polar Data Centre (PDC)"}
    assert all(r["date_added"] == "2026-10-11" for r in v3)
    grouped = json.loads((settings.v3_dir / "latest_results.json").read_text())
    assert sum(len(v) for v in grouped.values()) == 5
    filtered = read_csv(settings.v3_dir / "filtered_out_df.csv")
    assert [r["pub_doi"] for r in filtered] == ["10.1234/old-paper"]          # the excluded link


def test_first_seen_survives_and_seeds_from_v3(con, settings):
    settings.v3_dir.mkdir(parents=True)
    with open(settings.v3_dir / "latest_results.csv", "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=V3_COLUMNS)
        writer.writeheader()
        writer.writerow({"data_doi": A, "publication_doi": "10.1234/ARTICLE-X", "date_added": "2025-10-15"})
    run_all(con, settings, World())
    links = {(r["data_doi"], r["citing_id"]): r for r in read_csv(settings.v4_dir / "links.csv")}
    assert links[(A, "10.1234/article-x")]["first_seen"] == "2025-10-15"
    assert links[(A, "10.1234/meta-paper")]["first_seen"] == "2026-10-11"


def test_failed_source_blocks_publishing_and_keeps_results(con, settings):
    world = World()
    run_all(con, settings, world)
    before = (settings.v4_dir / "links.csv").read_text()

    world.scholix_fail = {A, B, C}
    client = world.client()
    assert run_harvest(make_ctx(con, client, settings), "scholexplorer") == "partial"
    assert run_works(con, client, settings) == "success"
    assert run_merge(con, settings) == "success"
    assert run_publish(con, settings) == "blocked"
    assert (settings.v4_dir / "links.csv").read_text() == before
    assert "scholexplorer" in db.latest_run(con, "publish")["message"]

    # The next run resumes the same harvest and only retries what failed.
    world.scholix_fail = set()
    client = world.client()
    partial_run = db.latest_run(con, "harvest", "scholexplorer")["run_id"]
    assert run_harvest(make_ctx(con, client, settings), "scholexplorer") == "success"
    assert db.good_run(con, "scholexplorer")["good_run_id"] == partial_run
    assert run_merge(con, settings) == "success"
    assert run_publish(con, settings) == "success"


def test_a_harvest_that_loses_most_rows_is_rejected(con, settings):
    world = World()
    run_all(con, settings, world)
    good = db.good_run(con, "scholexplorer")["good_run_id"]
    world.scholix_empty = True
    assert run_harvest(make_ctx(con, world.client(), settings), "scholexplorer") == "rejected"
    assert db.good_run(con, "scholexplorer")["good_run_id"] == good       # the previous harvest is still used
    assert run_publish(con, settings) == "blocked"


def test_a_real_drop_can_be_accepted(con, settings):
    world = World()
    run_all(con, settings, world)
    world.scholix_empty = True
    ctx = make_ctx(con, world.client(), settings)
    assert run_harvest(ctx, "scholexplorer") == "rejected"

    settings.accept_drop = frozenset({"scholexplorer"})
    assert run_harvest(ctx, "scholexplorer") == "success"
    latest = db.latest_run(con, "harvest", "scholexplorer")
    assert db.good_run(con, "scholexplorer")["good_run_id"] == latest["run_id"]
    assert json.loads(latest["details"])["accepted_drop"]["rows"] == 0
    assert run_works(con, world.client(), settings) == "success"
    assert run_merge(con, settings) == "success"

    # The published links fell too; that is accepted for this source only.
    settings.accept_drop = frozenset()
    assert run_publish(con, settings) == "blocked"
    assert "--accept-drop scholexplorer" in db.latest_run(con, "publish")["message"]
    settings.accept_drop = frozenset({"scholexplorer"})
    assert run_publish(con, settings) == "success"
    manifest = json.loads((settings.v4_dir / "manifest.json").read_text())
    assert any("scholexplorer" in w and "accepted" in w for w in manifest["guards"]["warnings"])
    assert not manifest["guards"]["forced"]


def test_a_partial_harvest_is_resumed_by_next_weeks_run(con, settings):
    world = World()
    run_all(con, settings, world)
    world.scholix_fail = {A, B, C}
    assert run_harvest(make_ctx(con, world.client(), settings), "scholexplorer") == "partial"
    partial_run = db.latest_run(con, "harvest", "scholexplorer")["run_id"]
    con.execute("UPDATE runs SET started_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-7 days') WHERE run_id=?",
                (partial_run,))
    con.commit()
    world.scholix_fail = set()
    assert run_harvest(make_ctx(con, world.client(), settings), "scholexplorer") == "success"
    assert db.good_run(con, "scholexplorer")["good_run_id"] == partial_run


def test_a_failed_metadata_lookup_is_retried_next_run(con, settings):
    world = World()
    world.crossref_fail = {"10.1234/article-x"}
    run_all(con, settings, world)
    work = con.execute("SELECT * FROM works WHERE citing_id='10.1234/article-x'").fetchone()
    assert work["metadata_source"] == "scholexplorer" and work["fetched_at"] is None   # the hint, for now

    world.crossref_fail = set()
    assert run_works(con, world.client(), settings) == "success"
    work = con.execute("SELECT * FROM works WHERE citing_id='10.1234/article-x'").fetchone()
    assert work["metadata_source"] == "crossref" and work["issued"] == "2021-05-01"
    assert work["fetched_at"] is not None


def test_incomplete_inventory_is_not_used(con, settings):
    world = World()
    client = world.client()
    assert run_inventory(con, client, settings.client_id) == "success"
    world.total = 4                                    # DataCite says 4, we can only find 3
    assert run_inventory(con, world.client(), settings.client_id) == "failed"
    assert con.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 3
    assert "4" in db.latest_run(con, "inventory")["message"]


def test_overton_without_key_is_skipped_not_failed(con, settings):
    settings.overton_api_key = None
    world = World()
    statuses, published = run_all(con, settings, world)
    assert statuses["overton"] == "skipped"
    assert published == "success"                      # optional source: a warning, not a block
    manifest = json.loads((settings.v4_dir / "manifest.json").read_text())
    assert any("overton" in w for w in manifest["guards"]["warnings"])

def test_v3_files_keep_the_v3_pipelines_types(con, settings):
    """The EDS citation API reads Results/v3: v3's float year, placeholders (never empty), columns, encodings."""
    from citations.publish import V3_FILTERED_COLUMNS, write_v3

    data = {
        "datasets": [{"doi": A, "data_centre": "NGDC", "data_centre_name": "National Geoscience Data Centre (NGDC)",
                      "publisher": NGDC, "title": None, "publication_year": 2020, "authors": []}],
        "works": [{"citing_id": "https://example.org/page", "title": None, "work_type": None, "container_title": None,
                   "publisher": None, "issued": "2021", "authors": [], "citation_text": "https://example.org/page"},
                  {"citing_id": "10.1234/old", "title": "Old", "work_type": "journal-article", "container_title": "J",
                   "publisher": "P", "issued": "2015-03", "authors": [{"given": "Ann", "family": "Smith"}],
                   "citation_text": "Smith (2015). Old."}],
        "links": [{"data_doi": A, "citing_id": "https://example.org/page", "citing_id_type": "url", "counted": True,
                   "status": "included", "relation_type": "IsCitedBy", "sources": ["datacite:metadata"],
                   "first_seen": "2026-10-01", "exclusion_reason": None},
                  {"data_doi": A, "citing_id": "10.1234/old", "citing_id_type": "doi", "counted": False,
                   "status": "excluded", "relation_type": "IsCitedBy", "sources": ["scholexplorer"],
                   "first_seen": "2026-10-01", "exclusion_reason": "predates-data"}],
    }
    write_v3(settings, data)

    raw = (settings.v3_dir / "latest_results.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")                                    # BOM, as v3 wrote it
    row = read_csv(settings.v3_dir / "latest_results.csv", encoding="utf-8-sig")[0]
    assert row["data_publication_year"] == "2020.0"
    assert row["data_title"] == "No title given"
    assert row["publication_title"] == row["pub_publisher"] == row["publication_type"] == "Info not given"
    assert row["publication_date"] == "2021"                                     # dates are not padded

    raw = (settings.v3_dir / "filtered_out_df.csv").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")                                # no BOM, as v3 wrote it
    filtered = read_csv(settings.v3_dir / "filtered_out_df.csv")
    assert list(filtered[0]) == V3_FILTERED_COLUMNS and len(V3_FILTERED_COLUMNS) == 14
    assert filtered[0]["data_publication_year"] == "2020.0" and filtered[0]["pub_date"] == "2015-03"

    text = (settings.v3_dir / "latest_results.json").read_text(encoding="utf-8")
    assert "\n" not in text                                                    # one line
    record = json.loads(text)["National Geoscience Data Centre (NGDC)"][0]
    assert isinstance(record["data_publication_year"], float)
    assert None not in (record["data_title"], record["publication_title"], record["pub_publisher"],
                        record["publication_type"], record["PubCitationStr"])
