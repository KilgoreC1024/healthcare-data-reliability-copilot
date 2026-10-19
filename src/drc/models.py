"""The shared data model: incidents, evidence bundles, investigations, and remediation proposals.

An *incident* is the alert a pipeline raised (a blocked publish, a failed or stalled run, or a publish with
warnings). A *collector* turns a platform's native operational metadata (run ledger, contract reports, dbt
artifacts, task logs) into an `IncidentBundle`: the incident plus a standard evidence record. Everything
downstream of a collector (tools, investigators, evaluation) is platform-agnostic.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Signal = Literal["run_blocked", "run_failed", "run_stalled", "published_with_warnings"]

ConsumerImpact = Literal[
    "previous_version_served",  # nothing from this run reached consumers
    "published_with_warning",  # the run published; a non-blocking check warned
    "published_with_quarantine",  # the run published; some rows were held back in quarantine
    "inconsistent_data_served",  # consumers can currently see data that failed a check or is known wrong
    "unknown",
]


class Incident(BaseModel):
    """What the on-call engineer (or the copilot) sees first: the alert, not the diagnosis."""

    incident_id: str
    platform: str
    pipeline: str
    run_id: str
    detected_at: str
    signal: Signal
    failed_stage: str | None = None
    headline: str


class Catalog(BaseModel):
    """Platform-level context that changes rarely: contracts, lineage, consumers, and runbooks."""

    platform: str
    sources: list[str]
    contracts: dict[str, Any] = Field(default_factory=dict)
    lineage: dict[str, Any] = Field(default_factory=dict)
    consumers: list[dict[str, Any]] = Field(default_factory=list)
    knowledge: list[dict[str, str]] = Field(default_factory=list)


class Evidence(BaseModel):
    """Run-level evidence recorded at incident time. Every field is optional: collectors fill what the
    platform actually records, and the copilot must cope with gaps (that is part of what is evaluated)."""

    run: dict[str, Any] = Field(default_factory=dict)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    check_details: dict[str, Any] = Field(default_factory=dict)
    schemas: dict[str, Any] = Field(default_factory=dict)
    profiles: dict[str, Any] = Field(default_factory=dict)
    releases: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    publish_state: dict[str, Any] = Field(default_factory=dict)
    logs: dict[str, str] = Field(default_factory=dict)


class IncidentBundle(BaseModel):
    schema_version: int = 1
    incident: Incident
    evidence: Evidence


# ---- investigation output ------------------------------------------------------------------------------
class Citation(BaseModel):
    """A claim tied to the exact tool call and the verbatim text in that call's output that supports it."""

    claim: str
    tool_call_id: str
    quote: str
    verified: bool | None = None  # set by the grounding verifier, never by the investigator


class Proposal(BaseModel):
    action_type: str
    target: str
    description: str
    risk: Literal["low", "medium", "high"]
    # Set by the policy engine. Investigators cannot approve or execute anything.
    policy_status: Literal["allowed", "rejected"] | None = None
    policy_reason: str | None = None


class Diagnosis(BaseModel):
    status: Literal["diagnosed", "abstained"]
    category: str | None = None
    summary: str
    source: str | None = None
    columns: list[str] = Field(default_factory=list)
    consumer_impact: ConsumerImpact = "unknown"
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Citation] = Field(default_factory=list)
    remediation: list[Proposal] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    abstain_reason: str | None = None


class ToolCall(BaseModel):
    call_id: str  # short id shown to the investigator in the tool result (call_01, ...)
    api_id: str | None = None  # the API's tool_use id, kept for tracing
    name: str
    arguments: dict[str, Any]
    output: str
    is_error: bool = False
    duration_ms: float = 0.0


class Usage(BaseModel):
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    turns: int = 0


class Investigation(BaseModel):
    incident: Incident
    investigator: str
    diagnosis: Diagnosis
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    latency_s: float = 0.0
    trace_id: str | None = None
    guardrail_events: list[str] = Field(default_factory=list)
