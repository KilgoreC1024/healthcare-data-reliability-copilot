"""Human-readable rendering of an investigation."""

from __future__ import annotations

from drc.models import Investigation
from drc.taxonomy import CATEGORIES


def render(inv: Investigation, show_tools: bool = True) -> str:
    d = inv.diagnosis
    i = inv.incident
    title = CATEGORIES[d.category].title if d.category in CATEGORIES else None
    lines = [
        f"Incident {i.incident_id}  |  {i.platform} / {i.pipeline}  |  run {i.run_id}",
        f"Signal: {i.signal}" + (f" at stage '{i.failed_stage}'" if i.failed_stage else ""),
        f"Alert:  {i.headline[:300]}",
        "",
    ]
    if d.status == "diagnosed":
        lines.append(f"DIAGNOSIS  {title} [{d.category}]  confidence {d.confidence:.2f}")
    else:
        lines.append("ABSTAINED  no root cause asserted")
        lines.append(f"  reason: {d.abstain_reason}")
    if d.summary:
        lines.append(f"  {d.summary}")
    if d.source or d.columns:
        lines.append(
            f"  where: {d.source or '-'}" + (f"  columns: {', '.join(d.columns)}" if d.columns else "")
        )
    lines.append(f"  consumer impact: {d.consumer_impact}")
    lines += ["", "Evidence"]
    for c in d.evidence:
        mark = "verified  " if c.verified else "UNVERIFIED"
        lines.append(f"  [{mark}] {c.claim}")
        lines.append(f'               {c.tool_call_id}: "{c.quote[:150]}"')
    if not d.evidence:
        lines.append("  (none)")
    lines += ["", "Proposed remediation (nothing runs without a named human approver)"]
    for n, p in enumerate(d.remediation, start=1):
        lines.append(
            f"  {n}. {p.action_type} -> {p.target}  [risk {p.risk}; policy {p.policy_status}: {p.policy_reason}]"
        )
        if p.description:
            lines.append(f"     {p.description[:200]}")
    if d.open_questions:
        lines += ["", "Open questions"] + [f"  - {q}" for q in d.open_questions]
    if inv.guardrail_events:
        lines += ["", "Guardrail events"] + [f"  - {e}" for e in inv.guardrail_events]
    if show_tools:
        lines += ["", f"Tool calls ({len(inv.tool_calls)})"]
        for t in inv.tool_calls:
            args = ", ".join(f"{k}={v!r}" for k, v in t.arguments.items())
            lines.append(f"  {t.call_id}  {t.name}({args}){'  ERROR' if t.is_error else ''}")
    u = inv.usage
    lines += [
        "",
        f"{inv.investigator}: {inv.latency_s:.1f} s"
        + (
            f", {u.turns} model turns, {u.input_tokens + u.cache_read_tokens + u.cache_write_tokens:,} input tokens "
            f"({u.cache_read_tokens:,} from cache), {u.output_tokens:,} output tokens, ${u.cost_usd:.3f}"
            if u.turns
            else ""
        ),
    ]
    return "\n".join(lines)
