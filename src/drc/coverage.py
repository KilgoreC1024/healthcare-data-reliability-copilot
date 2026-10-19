"""Investigation coverage: a confident diagnosis has to have looked at what the delivery changed.

The grounding check proves that every quote is in the record. It cannot see evidence that was never
gathered. On INC-H21 every citation verified, yet the diagnosis explained the alert (four new columns) and
missed the silent unit change that reached consumers, because the investigator never profiled the delivery.

The rule is deterministic, and like the remediation policy it reads the evidence, not the investigator's
claims:
  * it applies to a diagnosis (an abstention already goes to a person) when this run's output reached
    consumers (`policy.run_reached_consumers`), where a wrong conclusion leaves wrong data in front of them;
  * for every source this run delivered, the investigator must have seen the delivery's column profile: a
    successful `profile_columns` call on that source that returned the overview of changed columns (an empty
    column list) or named the column that overview ranks first. Profiling only the columns the alert names
    does not count, because that confirms the alert's explanation and can still miss the larger change;
  * a delivery whose profile shows no change has nothing to examine.
A diagnosis that fails keeps its category, confidence and proposals, but is marked `needs_review`, and a
guardrail event names the profile that was not examined and the columns it ranks as most changed.

Nothing here judges whether the diagnosis is right. It reads only the tool-call record and the evidence, so
it gives a recorded investigation (`replay`) the verdict it would have had when the run happened.
"""

from __future__ import annotations

import json

from drc.models import Diagnosis, IncidentBundle, Investigation, ToolCall
from drc.policy import run_reached_consumers
from drc.tools import changed_columns

EVENT_PREFIX = "needs review (coverage):"
NAMED_COLUMNS = 5
NAME_CHARS = 48


def _name(column: str) -> str:
    """A column name as data. Names come from upstream files and can carry text written for the reader (an
    adversarial incident plants instructions in one), so the reason quotes and shortens them."""
    return json.dumps(
        column if len(column) <= NAME_CHARS else column[:NAME_CHARS] + "...", ensure_ascii=False
    )


def _profiled(calls: list[ToolCall], source: str) -> list[list[str]]:
    """The column lists of every successful profile_columns call on a source ([] is the overview)."""
    return [
        list(c.arguments.get("columns") or [])
        for c in calls
        if c.name == "profile_columns" and not c.is_error and c.arguments.get("source") == source
    ]


def unexamined_profiles(
    calls: list[ToolCall], bundle: IncidentBundle, top_column: bool = True
) -> dict[str, list[str]]:
    """Sources delivered in this run whose changed column profile the investigator did not examine, each with
    its changed columns in the order profile_columns ranks them. With `top_column=False`, any successful
    profile_columns call on the source counts (the plain rule, kept for comparison in the replay report)."""
    missing = {}
    for source, info in bundle.evidence.profiles.items():
        ranked = changed_columns(info or {})
        if not ranked:
            continue
        profiled = _profiled(calls, source)
        examined = any(not cols or not top_column or ranked[0] in cols for cols in profiled)
        if not examined:
            missing[source] = ranked
    return missing


def check(
    diagnosis: Diagnosis, calls: list[ToolCall], bundle: IncidentBundle, top_column: bool = True
) -> tuple[Diagnosis, list[str]]:
    missing = (
        unexamined_profiles(calls, bundle, top_column)
        if diagnosis.status == "diagnosed" and run_reached_consumers(bundle)
        else {}
    )
    if not missing:
        return diagnosis.model_copy(update={"needs_review": False, "review_reason": None}), []
    parts = []
    for source, ranked in missing.items():
        profiled = sorted({col for cols in _profiled(calls, source) for col in cols})
        how = (
            f"profiled only {', '.join(map(_name, profiled))}" if profiled else "profile_columns never called"
        )
        more = ", ..." if len(ranked) > NAMED_COLUMNS else ""
        parts.append(f"{source} ({how}; most changed: {', '.join(map(_name, ranked[:NAMED_COLUMNS]))}{more})")
    reason = (
        "This run's output reached consumers, and the column profile of what it delivered was not examined: "
        + "; ".join(parts)
        + ". Check those columns before acting on this diagnosis."
    )
    flagged = diagnosis.model_copy(update={"needs_review": True, "review_reason": reason})
    return flagged, [f"{EVENT_PREFIX} {reason}"]


def replay(investigation: Investigation, bundle: IncidentBundle, top_column: bool = True) -> Investigation:
    """A recorded investigation as `finalize` would return it with this guardrail, for runs that predate it.
    A coverage verdict already recorded is replaced, so replaying is idempotent."""
    if investigation.incident.incident_id != bundle.incident.incident_id:
        raise ValueError(
            f"bundle {bundle.incident.incident_id} does not belong to {investigation.incident.incident_id}"
        )
    diagnosis, events = check(investigation.diagnosis, investigation.tool_calls, bundle, top_column)
    kept = [e for e in investigation.guardrail_events if not e.startswith(EVENT_PREFIX)]
    return investigation.model_copy(update={"diagnosis": diagnosis, "guardrail_events": [*kept, *events]})
