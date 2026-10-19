# ADR 0003: A benchmark built from real pipeline runs, with labels kept apart

**Status:** Accepted · **Date:** 2026-10-18

## Context

An incident copilot is only as credible as its evaluation. Hand-written incident descriptions would be
easy to produce and easy to game: the author controls both the question and how obvious the answer is.
The two pipelines this project builds on already contain the raw material for something better:
[hcip](https://github.com/KilgoreC1024/healthcare-cost-utilization-platform) has 13 fault-injection
scenarios that run the real pipeline against corrupted inputs, and the
[clinical ETL](https://github.com/KilgoreC1024/airflow-synthetic-clinical-etl) has code-defined quality
gates that fail on malformed FHIR-shaped data.

## Decision

1. **Incidents come from real runs.** `drc lab hcip` runs hcip's own pipeline (land, contract, bronze,
   dbt build and audit, publish) for each of `hcip.chaos.SCENARIOS` plus six scenarios the lab adds.
   `drc lab clinical` runs the clinical DAG's task callables in dependency order with its retry policy.
   The platform collector then records the evidence an on-call engineer would find: the run ledger,
   contract reports with samples, dbt results and the failing rows of audit queries, column profiles of
   the delivery and the previous one, lineage, publish state, and logs.
2. **Labels live in one file the investigators cannot read** (`benchmark/labels.yml`). Bundles get opaque
   ids (`INC-H07`), every scenario delivers its fault under the same neutral release id, and temporary
   paths and user names are rewritten. The lab refuses to write a bundle that contains its scenario name,
   and `tests/test_benchmark_integrity.py` re-checks every bundle against every label.
3. **The answer key stays out of the knowledge base.** hcip's runbook, architecture, and contract ADRs are
   searchable; `docs/fault-injection.md`, which maps each scenario to the check that catches it, is not.
4. **Three splits.** *Known* incidents have a root cause in the taxonomy and enough evidence to find it.
   *Novel* incidents do not support a specific root cause (a killed process with no output, a run that
   stopped with every step healthy, rows deleted outside the pipeline), so the correct answer is to
   abstain. *Adversarial* incidents plant prompt-injection text in column names, values, and record fields.
5. **Bundles are committed.** CI and anyone cloning the repository evaluate the same frozen evidence
   without either pipeline installed. The lab can regenerate everything from the pipeline repositories.

## Consequences

- Benchmark size is bounded by scenario authoring (30 incidents in release 1). That is enough to measure
  correctness and safety behavior and to show regressions, not enough for tight confidence intervals. The
  evaluation reports counts next to rates for that reason.
- The hcip fixtures are a real-data subset (583 CMS rows, 4,910 CDC rows), so profiles are smaller than
  production, but the failure signatures are the ones the real pipeline produces.
- Regenerated bundles differ in run ids and timestamps; labels and incident ids are stable.
