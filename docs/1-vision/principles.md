---
title: Principles
status: current
updated: 2026-11-26
---

# Principles

> The rules the pipeline is built around. Most of them answer a problem found in the v3 notebooks in October 2026.

## 1. Never publish a broken source as if it had found nothing

A harvest only replaces the previous one when it succeeds. Before anything is published, the [guards](../3-features/publishing-and-guards.md) check that every required source has a recent, successful harvest and hasn't lost a large share of its links. If a check fails, publishing is refused and the previous results stay as they were.

*Why:* v3 published whatever each stage last committed. The Scholexplorer harvest was an empty file from January to September 2026 and v3 went out without it every week.

## 2. Nothing is silently dropped

A link that breaks an exclusion rule is published with `status = excluded` and an `exclusion_reason`, not deleted. Links to datasets no longer in the inventory, and anything a source returns that can't be used (an unknown relation, an identifier that can't be parsed), are counted in the run's details.

*Why:* v3 deleted filtered rows, and until September 2026 its pre-dates rule also dropped every row with no publication year without recording it.

## 3. Count only what is a citation

Every link keeps its relation, turned round to the dataset's side, and gets a [relation class](../2-specification/counting-rules.md). Only included `citation` and `supplement` links are counted. Similarity recommendations, versions, parts and links between NERC datasets are published as related links.

*Why:* v3 counted every Scholexplorer relation as a citation; similarity recommendations alone were 44% of its rows.

## 4. Keep the evidence

Every source that reported a link is listed in `sources`, and the relation each one reported is kept in `source_relations`. Identifiers are normalised so the same work from two sources is one link, credited to both.

## 5. Don't break the people reading the results

The EDS citation API, the citation widget and the data centres' catalogues read the published files. `Results/v3` keeps the v3 pipeline's exact columns, encodings and types while consumers move to `Results/v4`, and the inspection notebook checks it against upstream's files. Results are only ever written atomically, and the manifest records a hash of every file so a reader can tell it has one consistent set.

## 6. Be polite to the APIs

Every request goes through one HTTP client that keeps to each API's published rate limit, sends a contact email where the API asks for one, retries with backoff, and honours `Retry-After`. Rate-limited responses are counted and recorded with each run.

## 7. Resume rather than repeat

Everything is cached in the store. An interrupted or partial harvest resumes and only retries what failed; citing-work metadata is fetched once and refreshed after 90 days; each citation string is made once. A run stopped by the GitHub job's time limit keeps what it fetched.

## 8. Test without the network

The whole pipeline runs in the tests against a fake world of APIs, including failures, drops and resumes. The tests take seconds and need no keys.

## 9. Keep secrets out of the code

API keys come from the environment (repository secrets in Actions) and are redacted from every log and error message.

*Why:* v3's Overton key was committed in the code. It is still in the git history and should be rotated.

## 10. Plain, readable code and outputs

Plain CSV and JSON in git, so anyone can diff a week's change. Plain Python with two dependencies. Every module, class and function has a docstring saying what it does and why. See [Documentation](../5-technical/documentation.md).
