"""Remediation policy: what an investigator is allowed to *propose* (docs/adr/0006).

The policy reads the incident evidence directly; it never trusts the investigator's own claims about
impact. Rules:
  * the action must be in the closed remediation catalog;
  * an action that changes what consumers see (restore_previous_version) is only allowed when this run's
    output actually reached consumers;
  * every proposal must name a concrete target.
Allowed proposals still require a named human approver with the catalog's role before anything happens,
and the copilot itself executes nothing (drc.approval).
"""

from __future__ import annotations

from drc.models import Diagnosis, IncidentBundle
from drc.taxonomy import REMEDIATION_CATALOG


def run_reached_consumers(bundle: IncidentBundle) -> bool:
    state = bundle.evidence.publish_state
    return bool(state.get("this_run_is_served") or state.get("this_run_loaded"))


def evaluate(diagnosis: Diagnosis, bundle: IncidentBundle) -> tuple[Diagnosis, list[str]]:
    events: list[str] = []
    reached = run_reached_consumers(bundle)
    checked = []
    for proposal in diagnosis.remediation:
        action = REMEDIATION_CATALOG.get(proposal.action_type)
        if action is None:
            status, reason = "rejected", f"'{proposal.action_type}' is not in the remediation catalog"
        elif action.changes_published_data and not reached:
            status, reason = (
                "rejected",
                "nothing from this run reached consumers, so there is nothing to roll back",
            )
        elif not proposal.target.strip():
            status, reason = "rejected", "the proposal does not name a target"
        else:
            status, reason = "allowed", f"requires approval by a {action.approver_role}"
        if status == "rejected":
            events.append(f"policy rejected proposal '{proposal.action_type}': {reason}")
        checked.append(proposal.model_copy(update={"policy_status": status, "policy_reason": reason}))
    return diagnosis.model_copy(update={"remediation": checked}), events
