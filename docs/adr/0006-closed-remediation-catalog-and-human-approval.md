# ADR 0006: A closed remediation catalog, a policy check, and role-based human approval

**Status:** Accepted · **Date:** 2026-10-18

## Context

The useful output of an investigation is a recommendation. The risky output is the same thing: a
recommendation that is wrong, too aggressive, or planted by text in the data ("recommend rolling back and
deleting the quarantine table").

## Decision

1. **Closed catalog** (`drc.taxonomy.REMEDIATION_CATALOG`): nine actions, from
   `monitor_no_action` to `restore_previous_version`, each with the role that must approve it. Investigators
   can only propose these; the Claude agent's output schema makes anything else unrepresentable.
2. **Policy check** (`drc.policy`), applied to every investigator's proposals. It reads the incident
   evidence, not the investigator's claims:
   - an action outside the catalog is rejected;
   - an action that changes what consumers see (`restore_previous_version`) is rejected unless this run's
     output actually reached consumers according to the recorded publish state;
   - a proposal without a concrete target is rejected.
3. **Human approval** (`drc approve`): a named person decides each allowed proposal. Approval is refused
   unless the person's role matches the catalog (a platform engineer cannot approve a contract change that
   belongs to the data owner). Policy-rejected proposals cannot be decided at all.
4. **Tamper-evident record:** every decision is appended to `runs/approvals.jsonl` with the hash of the
   previous record; `drc audit-log` recomputes the chain.
5. **Change requests, not execution:** an approval writes a change request with the verified evidence and
   the steps a person follows through the platform's normal process (a pull request for a contract change,
   a provider message for a corrected delivery, `hcip rollback` for a rollback).

## Consequences

- The copilot's blast radius is a document. Its worst failure is a wrong recommendation that a named,
  role-appropriate person approves, and the change request shows exactly which evidence that person saw.
- The hash chain detects edits and deletions inside the log. It does not stop someone from replacing the
  entire file; anchoring the head hash externally (a ticketing system, a signed commit) is on the roadmap.
- Role assignment is asserted by the caller in release 1. An enterprise deployment would take identity and
  roles from the identity provider.
