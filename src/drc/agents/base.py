"""The investigator interface and the post-processing every investigation goes through."""

from __future__ import annotations

from typing import Protocol

from drc import coverage, grounding, policy
from drc.models import Catalog, Diagnosis, IncidentBundle, Investigation, Usage
from drc.tools import ToolRegistry
from drc.tracing import Tracer


class Investigator(Protocol):
    name: str

    def investigate(
        self, bundle: IncidentBundle, catalog: Catalog, tracer: Tracer | None = None
    ) -> Investigation: ...


def finalize(
    investigator: str,
    bundle: IncidentBundle,
    registry: ToolRegistry,
    diagnosis: Diagnosis,
    usage: Usage,
    latency_s: float,
    tracer: Tracer,
    events: list[str] | None = None,
) -> Investigation:
    """Apply the grounding check, the remediation policy and the coverage check, whatever produced the
    diagnosis."""
    with tracer.span("guardrails.grounding") as span:
        diagnosis, grounding_events = grounding.verify(diagnosis, registry.calls)
        span.set(
            citations=len(diagnosis.evidence), verified=sum(bool(c.verified) for c in diagnosis.evidence)
        )
    with tracer.span("guardrails.policy") as span:
        diagnosis, policy_events = policy.evaluate(diagnosis, bundle)
        span.set(proposals=len(diagnosis.remediation))
    with tracer.span("guardrails.coverage") as span:
        diagnosis, coverage_events = coverage.check(diagnosis, registry.calls, bundle)
        span.set(needs_review=diagnosis.needs_review)
    return Investigation(
        incident=bundle.incident,
        investigator=investigator,
        diagnosis=diagnosis,
        tool_calls=registry.calls,
        usage=usage,
        latency_s=round(latency_s, 3),
        trace_id=tracer.trace_id,
        guardrail_events=[
            *(events or []),
            *registry.guardrail_events,
            *grounding_events,
            *policy_events,
            *coverage_events,
        ],
    )
