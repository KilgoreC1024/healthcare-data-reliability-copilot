"""Human approval for remediation proposals (docs/adr/0006).

The copilot never executes remediation. A proposal that passed the policy check can be approved or
rejected by a named person holding the role the remediation catalog requires. Every decision is appended
to a hash-chained JSON-lines log, so any edit or deletion of an earlier decision is detectable. An
approval produces a change request: a document a human uses to carry out the action through the
platform's normal process (a pull request, a ticket, a provider message, a CLI command).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from drc.models import Investigation, Proposal
from drc.taxonomy import CATEGORIES, REMEDIATION_CATALOG

GENESIS = "0" * 64


class ApprovalError(ValueError):
    pass


def _hash(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _last_hash(log: Path) -> str:
    if not log.is_file():
        return GENESIS
    lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return json.loads(lines[-1])["hash"] if lines else GENESIS


def decide(
    investigation: Investigation,
    proposal_number: int,
    approver: str,
    role: str,
    decision: Literal["approve", "reject"],
    note: str,
    log: Path,
    change_request_dir: Path,
) -> dict[str, Any]:
    proposals = investigation.diagnosis.remediation
    if not 1 <= proposal_number <= len(proposals):
        raise ApprovalError(
            f"proposal {proposal_number} does not exist (this investigation has {len(proposals)})"
        )
    proposal = proposals[proposal_number - 1]
    if proposal.policy_status != "allowed":
        raise ApprovalError(
            f"the policy check rejected this proposal ({proposal.policy_reason}); it cannot be decided"
        )
    if not approver.strip():
        raise ApprovalError("an approver name is required")
    action = REMEDIATION_CATALOG[proposal.action_type]
    if decision == "approve" and role != action.approver_role:
        raise ApprovalError(f"'{action.id}' must be approved by a {action.approver_role}, not a {role}")
    record: dict[str, Any] = {
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "incident_id": investigation.incident.incident_id,
        "run_id": investigation.incident.run_id,
        "investigator": investigation.investigator,
        "trace_id": investigation.trace_id,
        "diagnosis_status": investigation.diagnosis.status,
        "diagnosis_category": investigation.diagnosis.category,
        "diagnosis_needs_review": investigation.diagnosis.needs_review,
        "verified_citations": sum(bool(c.verified) for c in investigation.diagnosis.evidence),
        "proposal_number": proposal_number,
        "action_type": proposal.action_type,
        "target": proposal.target,
        "decision": decision,
        "approver": approver.strip(),
        "role": role,
        "note": note,
        "prev_hash": _last_hash(log),
    }
    if decision == "approve":
        change_request_dir.mkdir(parents=True, exist_ok=True)
        path = (
            change_request_dir
            / f"{investigation.incident.incident_id}-{proposal_number}-{proposal.action_type}.md"
        )
        path.write_text(render_change_request(investigation, proposal, record), encoding="utf-8")
        record["change_request"] = path.as_posix()
    record["hash"] = _hash(record)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def verify_log(log: Path) -> tuple[bool, int, str]:
    """Recompute the hash chain. Returns (ok, number of records, problem description)."""
    if not log.is_file():
        return True, 0, "no decisions recorded yet"
    previous = GENESIS
    lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    for number, line in enumerate(lines, start=1):
        record = json.loads(line)
        if record.get("prev_hash") != previous:
            return False, number, f"record {number} does not follow record {number - 1} (chain broken)"
        if _hash(record) != record.get("hash"):
            return False, number, f"record {number} was modified after it was written"
        previous = record["hash"]
    return True, len(lines), "chain intact"


STEPS = {
    "request_corrected_delivery": [
        "Send the data provider the verified evidence above and ask for a corrected delivery.",
        "When it arrives as a new release, re-run the pipeline; the contract and audit gates re-check it.",
    ],
    "amend_data_contract": [
        "Confirm with the provider that the change is intended and permanent.",
        "Open a pull request that updates the data contract (and any dependent transformation) and explains why.",
        "Merge only after CI passes; the next run validates the delivery against the amended contract.",
    ],
    "update_transformation": [
        "Open a pull request that teaches the transformation to handle the new input shape, with a test.",
        "Re-run the pipeline after merge.",
    ],
    "correct_source_records": [
        "Ask the source-system owner to correct the records named in the evidence.",
        "Re-run the pipeline once the corrected extract is available.",
    ],
    "review_quarantined_rows": [
        "Review the quarantined rows and their reasons with the data steward.",
        "Decide per row: request a correction upstream, or accept the exclusion.",
    ],
    "rerun_pipeline": ["Re-run the pipeline through its normal entry point after the cause is resolved."],
    "restore_previous_version": [
        "Identify the last audited run from the platform's status command.",
        "Re-point consumers to it with the platform's rollback procedure, then notify consumers.",
    ],
    "escalate_to_platform_oncall": ["Page the platform on-call and attach this document."],
    "monitor_no_action": ["No change now. Check the next run; reopen if the signal repeats or grows."],
}


def render_change_request(investigation: Investigation, proposal: Proposal, record: dict[str, Any]) -> str:
    d = investigation.diagnosis
    category = CATEGORIES[d.category].title if d.category in CATEGORIES else "not determined"
    lines = [
        f"# Change request: {proposal.action_type} for {investigation.incident.incident_id}",
        "",
        f"- **Approved by:** {record['approver']} ({record['role']}) at {record['decided_at']}",
        f"- **Pipeline / run:** {investigation.incident.pipeline} / {investigation.incident.run_id}",
        f"- **Target:** {proposal.target}",
        f"- **Risk:** {proposal.risk}",
        f"- **Diagnosis:** {category} ({d.status}, confidence {d.confidence:.2f})",
        f"- **Investigation trace:** {investigation.trace_id}",
    ]
    if d.needs_review:
        lines.append(f"- **Needs review (coverage check):** {d.review_reason}")
    lines += [
        "",
        "## Why",
        "",
        d.summary or (d.abstain_reason or ""),
        "",
        proposal.description,
        "",
        "## Verified evidence",
        "",
    ]
    lines += [f"- {c.claim}: `{c.quote}`" for c in d.evidence if c.verified] or ["- (none)"]
    lines += ["", "## Steps (performed by a person, outside the copilot)", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(STEPS[proposal.action_type], start=1)]
    if record.get("note"):
        lines += ["", "## Approver note", "", record["note"]]
    return "\n".join(lines) + "\n"
