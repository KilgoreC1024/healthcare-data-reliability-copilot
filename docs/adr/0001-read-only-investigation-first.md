# ADR 0001: Read-only investigation first

**Status:** Accepted · **Date:** 2026-10-18

## Context

An AI system that can both diagnose and change production data pipelines is attractive and dangerous.
Healthcare data has two properties that make the danger concrete: published numbers feed decisions about
cost, coverage, and care, and the people who own a feed (a data owner, a steward, a provider contact) are
not the people who run the platform. A wrong automated "fix" (rolling back a correct release, dropping
quarantined rows, loosening a contract) can do more damage than the incident it responds to.

The diagnostic half is also where most of the value is. On-call time goes into reading run ledgers,
contract reports, dbt logs, and lineage to answer "what broke, where, and who is affected?"

## Decision

Release 1 is an investigator, not an operator.

- The investigator's only tools read one incident's recorded evidence (`drc.tools`). There is no tool that
  writes, re-runs, or calls the network, so no prompt or bug can make the investigator change anything.
- Collectors that build that evidence open platform databases read-only (DuckDB `read_only=True`, SQLite
  `mode=ro`) and never call the pipeline.
- Remediation is a proposal from a closed catalog. It needs a named human approver with the right role,
  and approval produces a change request a person carries out through the platform's normal process
  ([ADR 0006](0006-closed-remediation-catalog-and-human-approval.md)).

## Consequences

- The copilot cannot shorten time-to-repair by acting on its own. It shortens time-to-diagnosis and makes
  the repair decision better informed. That is the right trade until the diagnostic layer is measured and
  trusted ([evaluation](../evaluation.md)).
- Automated execution of low-risk actions (for example, re-running a pipeline after a transient
  infrastructure failure) is a later, separate decision with its own evaluation and its own ADR.
