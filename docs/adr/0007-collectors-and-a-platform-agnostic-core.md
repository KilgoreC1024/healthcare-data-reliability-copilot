# ADR 0007: Collectors normalize platform metadata; everything after them is platform-agnostic

**Status:** Accepted · **Date:** 2026-10-18

## Context

The two pipelines record failures in very different shapes. hcip writes a DuckDB run ledger, JSON contract
reports, dbt artifacts, and a gold pointer file. The clinical ETL is an Airflow DAG: task instances with
states, retries, and logs, a FHIR-shaped JSON source, and a SQLite target. An enterprise has many more
(Fabric pipelines, Databricks jobs, ADF, dbt Cloud). If the investigator knew about each one, every new
platform would mean new prompts, new tools, and a new evaluation.

## Decision

A **collector** per platform converts native metadata into one `IncidentBundle`
(`drc.models`): an `Incident` (the alert) and an `Evidence` record with fixed sections (run and steps,
checks, check details, schemas, profiles, releases, publish state, logs). A per-platform `Catalog` carries
what changes rarely (contracts or code-defined gates, lineage, consumers, runbook sections).

Tools, investigators, grounding, policy, approval, and evaluation only see bundles and catalogs.

| Evidence section | hcip | Clinical ETL |
| --- | --- | --- |
| run / steps | `pipeline_runs`, `step_runs` | DAG run, task instances (state, try, duration) |
| checks | `check_results` (contract and dbt) | one check per quality gate (task) |
| check details | contract report samples; failing rows of the compiled dbt test | exception, records named in the error |
| schemas | landed header vs previous accepted release | FHIR field paths vs the previous source file |
| profiles | DuckDB column profiles of both deliveries | field profiles, unresolved references, naive timestamps |
| publish state | `lakehouse/gold/_CURRENT.json` | SQLite row counts, whether `load` committed |
| lineage | dbt `manifest.json` | the DAG's task graph and target tables |

## Consequences

- Onboarding a platform means writing a collector and a catalog entry in `src/drc/platforms.yml`; the
  benchmark measures whether the investigator transfers ([ADR 0004](0004-deterministic-baseline-as-control.md)).
- Collection is eager: a bundle contains every profile an investigation might ask for. That keeps live and
  benchmark investigations identical by construction, at the cost of profiling work (about one second for
  hcip's fixture-sized deliveries) that a lazy design would skip.
