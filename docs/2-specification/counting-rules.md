---
title: Counting rules
status: current
updated: 2026-11-26
---

# Counting rules

> What a link is, how it is classified, what is counted and what is excluded. The code is in `citations/relations.py`, `citations/filters.py` and `citations/merge.py`.

## Links

A **link** is one dataset and one citing work, with every source that reported it. Its id, `link_id`, is the SHA-1 of `data_doi|citing_id`, so the same pair has the same id in every run.

### Identifiers

Identifiers are normalised at harvest (`citations/ids.py`) so the same work from two sources becomes one link:

| Type | Form | Example |
| --- | --- | --- |
| `doi` | bare, lower case. A DOI anywhere in a URL's path is used, so `https://doi.org/10.1/X`, `doi:10.1/x` and a publisher URL ending `/doi/10.1/x` are one work | `10.1111/1365-2656.12728` |
| `url` | `https`, lower-case host without `www.`, no fragment, no tracking parameters (`utm_*`, `fbclid` ...), no trailing slash | `https://rand.org/pubs/research_reports/RR2695.html` |
| `pmid` | `pmid:` and the number | `pmid:123456` |
| `pmc` | `pmc:PMC` and the number | `pmc:PMC12345` |
| `handle` | `hdl:` and the handle | `hdl:10013/epic.1` |

A citing identifier equal to the dataset's own DOI is never a link. Different identifiers for the same work (a preprint and its article, a DOI and a repository URL) are **not** yet merged; see [Known limitations](#known-limitations).

## Relations

Relations are stored in the DataCite vocabulary *from the dataset's side*: `IsCitedBy` means the other work cites the dataset. A source that states the link from the citing work's side ("article References dataset") is turned round. How each source states its links:

| Source | States links as | Turned round? |
| --- | --- | --- |
| DataCite `relationships.citations` | labelled from DataCite events, which can put the dataset on either side | when the dataset is the event's object |
| DataCite `relatedIdentifiers` | the dataset is the subject | no |
| Scholexplorer | "source *relation* target", the dataset is the target | yes |
| Overton | a policy document cites the dataset | recorded as `IsReferencedBy` |
| Crossref data citations | the article is the subject, the dataset the object | yes, with Crossref's own relation names mapped first |

Relations where the dataset is the one citing or deriving (`References`, `Cites`, `IsDerivedFrom`, `IsCompiledBy` ...) are *outgoing*: they are not links to the dataset and are dropped at harvest, and counted in the run's details.

## Relation classes

| `relation_class` | From | Counted |
| --- | --- | --- |
| `citation` | `IsCitedBy`, `IsReferencedBy` | yes |
| `supplement` | `IsSupplementTo`, `IsSupplementedBy` (either direction: data centres write "dataset IsSupplementTo article", DataCite counts "article is-supplement-to dataset") | yes |
| `documentation` | `IsDocumentedBy`, `IsDescribedBy`, `IsReviewedBy` | no, related |
| `other` | `IsRequiredBy`, `IsSourceOf`, `Compiles` | no, related |
| `dataset-link` | any of the four classes above, where the citing work is itself a NERC dataset (`10.5285/...`) | no, related dataset |
| `version-or-part` | `IsPartOf`, `HasPart`, `IsNewVersionOf`, `IsPreviousVersionOf`, `HasVersion`, `IsVersionOf`, `Continues`, `IsContinuedBy`, `IsVariantFormOf`, `IsOriginalFormOf`, `Obsoletes`, `IsObsoletedBy`, `IsIdenticalTo` | no, related dataset |
| `similarity` | Scholexplorer `HasAmongTopNSimilarDocuments` | no, related dataset |

When sources disagree about one pair, the most specific class wins, in this order: `citation`, `supplement`, `documentation`, `other`, `version-or-part`, `similarity`. For example DataCite saying an article references a dataset beats Scholexplorer saying the two are similar.

**`counted`** is true for links that are *included* and of class `citation` or `supplement`. Catalogues and the widget should show the rest as related datasets and documents, never in the citation count.

**Preprints** are counted like any other citing work, whether or not they have since been published. A preprint and the article it became are not yet merged, so a dataset cited by both is counted twice (see [Known limitations](#known-limitations)).

## Exclusions

A link is **excluded**, but still published, when the first of these rules applies:

| `exclusion_reason` | Rule |
| --- | --- |
| `self-link` | the citing work is the dataset |
| `comment` | the title starts "Comment on", "Reply on", "Reply to comment by", "Final response" or "Author response" |
| `peer-review` | the work type is a peer review |
| `conference-abstract` | an EGU General Assembly abstract (`10.5194/egusphere-egu...`). Other EGUsphere DOIs are preprints and are counted |
| `gbif-download` | a GBIF download DOI (`10.15468/...`) |
| `predates-data` | the work was issued **two or more years** before the dataset's publication year. Applies to `citation`, `supplement`, `documentation` and `other` links only; a work with no known year is kept |

A year either way is normal (preprints, online-first articles, data deposited after acceptance), so only a gap of two years or more is excluded. The tolerance is the `predates_tolerance_years` setting.

## First and last seen

`first_seen` is the date a link was first found; `last_seen` the date of the latest run that still found it. Both are kept in the store's `link_history`, so a link that disappears and comes back keeps its first date. When the store is rebuilt from scratch, `first_seen` is seeded from the published `Results/v4/links.csv`, or, before v4 was ever published, from v3's `date_added`.

## Known limitations

**The same work under two identifiers is counted twice.** Links are de-duplicated on normalised identifiers, so different spellings of one DOI or URL become one link. Different identifiers for one work are not merged. Matching titles within each dataset in the October 2026 results found about 520 extra counted links (about 6%). Most are one of three kinds:

- **A preprint and its published article** (about 370 links). Most are Copernicus discussion papers and their final papers, such as `essd-2025-67` and `essd-18-1243-2026`. The rest are on servers such as bioRxiv, Research Square and EarthArXiv.
- **A DOI and the same work as an OpenAIRE or repository URL** (about 85 links).
- **Version DOIs of one Zenodo or figshare record** (about 20 links).

The planned fix:

1. Link a preprint to its article using Crossref's `is-preprint-of` relation. Copernicus deposits it, but some preprint servers don't, so where it is missing, fall back to a matching title and first author within one dataset.
2. Count the published version, and publish the preprint link as excluded with its own `exclusion_reason`.
3. Keep counting a preprint that has no published version.

This is the top item in the [backlog](../4-roadmap/backlog.md).
