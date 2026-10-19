"""Grounding verification, remediation policy, and the approval workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from drc import approval, grounding, policy
from drc.agents.baseline import BaselineInvestigator
from drc.models import Citation, Diagnosis, Proposal
from drc.tools import ToolRegistry


def _diagnosis(evidence, remediation=()):
    return Diagnosis(
        status="diagnosed",
        category="schema.required_column_missing",
        summary="x",
        confidence=0.8,
        evidence=list(evidence),
        remediation=list(remediation),
    )


def test_verbatim_quotes_verify_and_fabrications_do_not(load):
    reg = ToolRegistry(*load("INC-H01"))
    call = reg.call("list_failed_checks", {"include_warnings": False})
    good = Citation(claim="c", tool_call_id=call.call_id, quote="missing: TOT_MDCR_STDZD_PYMT_PC")
    invented = Citation(claim="c", tool_call_id=call.call_id, quote="missing: TOT_MDCR_PYMT_AMT")
    wrong_call = Citation(claim="c", tool_call_id="toolu_never_made", quote="missing: TOT_MDCR_STDZD_PYMT_PC")
    result, events = grounding.verify(_diagnosis([good, invented, wrong_call]), reg.calls)
    assert [c.verified for c in result.evidence] == [True, False, False]
    assert result.status == "diagnosed"
    assert len(events) == 2


def test_quotes_survive_json_escaping_and_whitespace(load):
    reg = ToolRegistry(*load("INC-H05"))
    call = reg.call("profile_columns", {"source": "cms_geo_variation", "columns": []})
    assert grounding.quote_in_output('"current": 0', call.output)
    assert grounding.quote_in_output("current:   0", call.output)
    assert not grounding.quote_in_output("0", call.output)  # too short to mean anything


def test_a_diagnosis_without_verified_evidence_is_withheld(load):
    reg = ToolRegistry(*load("INC-H01"))
    reg.call("get_run_overview", {})
    bogus = Citation(claim="c", tool_call_id="call_01", quote="the warehouse disk is full")
    result, events = grounding.verify(_diagnosis([bogus]), reg.calls)
    assert result.status == "abstained" and result.category is None
    assert "withheld" in result.abstain_reason
    assert "diagnosis withheld: no verified evidence" in events


def test_policy_rejects_rollback_when_nothing_reached_consumers(load):
    bundle, _ = load("INC-H01")
    proposals = [
        Proposal(action_type="restore_previous_version", target="gold", description="", risk="high"),
        Proposal(action_type="drop_quarantine_table", target="silver", description="", risk="high"),
        Proposal(action_type="request_corrected_delivery", target="", description="", risk="low"),
        Proposal(
            action_type="request_corrected_delivery", target="cms_geo_variation", description="", risk="low"
        ),
    ]
    result, events = policy.evaluate(_diagnosis([], proposals), bundle)
    assert [p.policy_status for p in result.remediation] == ["rejected", "rejected", "rejected", "allowed"]
    assert len(events) == 3


def test_policy_allows_rollback_when_inconsistent_data_was_served(load):
    bundle, _ = load("INC-C09")
    proposal = Proposal(
        action_type="restore_previous_version", target="clinical_demo.sqlite", description="", risk="high"
    )
    result, _ = policy.evaluate(_diagnosis([], [proposal]), bundle)
    assert result.remediation[0].policy_status == "allowed"


def test_approval_requires_the_catalog_role_and_chains_every_decision(load, tmp_path):
    investigation = BaselineInvestigator().investigate(*load("INC-H09"))
    log, crs = tmp_path / "approvals.jsonl", tmp_path / "cr"
    with pytest.raises(approval.ApprovalError, match="must be approved by a data_owner"):
        approval.decide(investigation, 1, "Sam", "platform_engineer", "approve", "", log, crs)
    record = approval.decide(investigation, 1, "Sam Rivera", "data_owner", "approve", "ok", log, crs)
    assert (tmp_path / "cr").glob("*.md") and record["prev_hash"] == approval.GENESIS
    approval.decide(investigation, 1, "Sam Rivera", "data_owner", "reject", "superseded", log, crs)
    assert approval.verify_log(log) == (True, 2, "chain intact")

    lines = log.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["approver"] = "Someone Else"
    log.write_text("\n".join([json.dumps(first), lines[1]]) + "\n", encoding="utf-8")
    ok, _, message = approval.verify_log(log)
    assert not ok and "modified" in message


def test_policy_rejected_proposals_cannot_be_approved(load, tmp_path):
    investigation = BaselineInvestigator().investigate(*load("INC-H01"))
    rejected = investigation.diagnosis.remediation[0].model_copy(
        update={"policy_status": "rejected", "policy_reason": "test"}
    )
    investigation.diagnosis.remediation[0] = rejected
    with pytest.raises(approval.ApprovalError, match="policy check rejected"):
        approval.decide(investigation, 1, "Sam", "data_owner", "approve", "", tmp_path / "a.jsonl", tmp_path)


def test_reports_and_change_requests_separate_verified_from_unverified_evidence(load, tmp_path):
    from drc.report import render

    investigation = BaselineInvestigator().investigate(*load("INC-H02"))
    planted = Citation(claim="planted", tool_call_id="call_01", quote="not in any output", verified=False)
    investigation.diagnosis.evidence.append(planted)
    text = render(investigation)
    assert "[UNVERIFIED] planted" in text and "[verified  ]" in text

    record = approval.decide(
        investigation, 1, "Ana Diaz", "data_owner", "approve", "", tmp_path / "log.jsonl", tmp_path / "cr"
    )
    change_request = Path(record["change_request"]).read_text(encoding="utf-8")
    assert "Location_ID" in change_request
    assert "not in any output" not in change_request
