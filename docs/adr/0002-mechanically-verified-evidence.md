# ADR 0002: Mechanically verified evidence

**Status:** Accepted · **Date:** 2026-10-18

## Context

A language model can write a fluent, plausible root-cause analysis that is not supported by anything it
looked at. Asking a second model to judge whether the evidence is convincing moves the problem rather than
solving it, and adds cost and variance. On-call engineers need to know which statements they can rely on
without re-doing the investigation.

## Decision

Every claim in a diagnosis carries a citation: the id of a tool call made during this investigation and a
short quote copied verbatim from that call's output. `drc.grounding` checks each citation mechanically:

- the tool call must exist and must have succeeded;
- the quote (at least 3 characters) must appear in the recorded output, after normalizing whitespace and
  JSON string escaping;
- nothing else is checked, and no model is involved.

Unverified citations are marked in the report and counted in evaluation. **A diagnosis with no verified
citation is withheld**: it is converted to an abstention that records the original category, so an
unsupported root cause never reaches a person as a conclusion.

The same rule applies to the deterministic baseline, so both investigators are held to one standard.

## Why

- Verification is cheap, deterministic, and explainable: "this quote is not in that output."
- Requiring verbatim quotes changes model behavior as well as catching errors: the instruction to quote
  exactly pushes the investigator to read the record rather than recall typical failure patterns.
- Call ids are assigned by the harness (`call_01`, `call_02`, ...) and printed on the first line of each
  tool result, so a citation cannot point at a call that did not happen. The first live run showed why the
  id has to be visible: the model cited tools by name, because the API's own `tool_use` ids are not
  something it can reliably read back. All seven of its quotes were verbatim, yet the grounding check
  correctly withheld the diagnosis. Results now carry the short id; the API id is kept for tracing and is
  also accepted.

## Consequences

- Verification proves that the quoted text exists, not that it supports the claim. A quote can be real and
  irrelevant. The evaluation measures root-cause correctness separately for that reason, and the change
  request shows the quotes so the approver can judge relevance.
- Paraphrased numbers ("about 40%") fail verification even when correct. The system prompt asks for exact
  substrings; the cost is some unverified-but-true citations, which the report shows as unverified.
