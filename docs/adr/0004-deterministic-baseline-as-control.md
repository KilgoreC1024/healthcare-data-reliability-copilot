# ADR 0004: A deterministic playbook as the control, and a held-out platform

**Status:** Accepted · **Date:** 2026-10-18

## Context

"The agent diagnosed 25 of 30 incidents" means little without a comparison. Many pipeline incidents can be
diagnosed by rules: if the contract says a required column is missing, the root cause is a missing column.
An LLM agent has to earn its cost and its risk against what a careful engineer could automate.

## Decision

`drc.agents.baseline` is a deterministic investigator that uses **the same tools, the same citation
format, the same grounding check, and the same policy** as the Claude agent. Its rules encode hcip's
check vocabulary (contract checks, dbt audit tests, quarantine reasons), profile comparisons (a mean that
moved by an exact power of ten is a unit change), and a few platform-independent infrastructure
signatures (missing file, locked resource). When no rule fires it abstains.

It deliberately has **no rules for the clinical ETL's quality-gate messages**. The clinical pipeline plays
the role of a newly onboarded platform: it measures how well each investigator transfers to failure
vocabulary it was not built for.

## Consequences

- The baseline scores 100% on hcip's known incidents by construction. That number is an upper bound on
  rule coverage, not evidence of generalization, and the evaluation says so.
- The comparison that matters is per split: known-hcip (can the agent match a purpose-built playbook?),
  known-clinical (does it transfer?), novel (does it know when not to answer?), and adversarial (does
  planted text change its behavior?).
- The baseline is also the degraded mode: if the model API is unavailable, the copilot still produces
  grounded diagnoses for the incidents its rules cover and abstains on the rest.
- The baseline is deterministic, so CI enforces its metrics as exact regression gates
  (`eval/gates/baseline.yml`). Any change to collectors, tools, or the benchmark that moves a number has
  to be deliberate.
