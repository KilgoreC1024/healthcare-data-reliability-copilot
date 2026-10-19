"""The Claude investigator's loop, exercised against a scripted fake client (no network, no API key)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from drc.agents.claude import FALLBACK_BETA, FINAL_TURN_NOTE, ClaudeInvestigator
from drc.agents.prompts import DIAGNOSIS_SCHEMA, SYSTEM_PROMPT


def tool_use(block_id: str, name: str, **arguments):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=arguments)


def text(value: str):
    return SimpleNamespace(type="text", text=value)


def response(*blocks, stop="tool_use", model="claude-opus-5-5", tokens=(1000, 200, 0, 0)):
    usage = SimpleNamespace(
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        cache_read_input_tokens=tokens[2],
        cache_creation_input_tokens=tokens[3],
    )
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop,
        model=model,
        usage=usage,
        _request_id="req_x",
        stop_details=None,
    )


class FakeClient:
    def __init__(self, *script):
        self.script = list(script)
        self.requests: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.requests.append({**params, "messages": [dict(m) for m in params["messages"]]})
        return self.script.pop(0)


def final_answer(**overrides) -> str:
    answer = {
        "status": "diagnosed",
        "category": "schema.required_column_missing",
        "summary": "CMS stopped delivering TOT_MDCR_STDZD_PYMT_PC.",
        "source": "cms_geo_variation",
        "columns": ["TOT_MDCR_STDZD_PYMT_PC"],
        "consumer_impact": "previous_version_served",
        "confidence": 0.9,
        "evidence": [
            {
                "claim": "the contract reports the column missing",
                "tool_call_id": "toolu_2",
                "quote": "missing: TOT_MDCR_STDZD_PYMT_PC",
            },
            {
                "claim": "nothing new was served",
                "tool_call_id": "toolu_3",
                "quote": '"this_run_is_served": false',
            },
        ],
        "remediation": [
            {
                "action_type": "request_corrected_delivery",
                "target": "cms_geo_variation",
                "description": "Ask CMS.",
                "risk": "medium",
            }
        ],
        "open_questions": [],
        "abstain_reason": "",
    }
    answer.update(overrides)
    return json.dumps(answer)


def test_investigation_loop_request_shape_and_evidence(load):
    client = FakeClient(
        response(
            tool_use("toolu_1", "get_run_overview"),
            tool_use("toolu_2", "list_failed_checks", include_warnings=False),
        ),
        response(tool_use("toolu_3", "get_downstream_impact", node="cms_geo_variation")),
        response(text(final_answer()), stop="end_turn"),
    )
    inv = ClaudeInvestigator(client=client).investigate(*load("INC-H01"))

    d = inv.diagnosis
    assert d.status == "diagnosed" and d.category == "schema.required_column_missing"
    assert [c.verified for c in d.evidence] == [True, True]
    assert d.remediation[0].policy_status == "allowed"
    assert [t.call_id for t in inv.tool_calls] == ["toolu_1", "toolu_2", "toolu_3"]

    first = client.requests[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["system"] == SYSTEM_PROMPT
    assert all(t["strict"] for t in first["tools"])
    assert first["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": DIAGNOSIS_SCHEMA},
    }
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["betas"] == [FALLBACK_BETA] and first["fallbacks"] == "default"
    assert "tool_choice" not in first and "temperature" not in first and "thinking" not in first

    # Parallel tool calls come back as one user message with one tool_result per tool_use id.
    second = client.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert [r["tool_use_id"] for r in second[2]["content"]] == ["toolu_1", "toolu_2"]

    assert inv.usage.turns == 3
    assert abs(inv.usage.cost_usd - 3 * (1000 * 4 + 200 * 20) / 1e6) < 1e-9


def test_write_tools_do_not_exist_and_attempts_are_recorded(load):
    client = FakeClient(
        response(tool_use("toolu_1", "delete_rows", table="silver.silver_quarantine")),
        response(tool_use("toolu_2", "list_failed_checks", include_warnings=False)),
        response(tool_use("toolu_3", "get_downstream_impact", node="cms_geo_variation")),
        response(text(final_answer()), stop="end_turn"),
    )
    inv = ClaudeInvestigator(client=client).investigate(*load("INC-H01"))
    assert inv.tool_calls[0].is_error and "not an available tool" in inv.tool_calls[0].output
    assert "refused unknown tool 'delete_rows'" in inv.guardrail_events


def test_budget_exhaustion_forces_a_final_answer_without_tools(load):
    client = FakeClient(
        response(
            tool_use("toolu_1", "get_run_overview"),
            tool_use("toolu_2", "list_failed_checks", include_warnings=False),
        ),
        response(tool_use("toolu_3", "get_downstream_impact", node="cms_geo_variation")),
        response(text(final_answer()), stop="end_turn"),
    )
    inv = ClaudeInvestigator(client=client, budget=2).investigate(*load("INC-H01"))
    last = client.requests[-1]
    assert last["tool_choice"] == {"type": "none"}
    assert last["messages"][-1]["content"][-1] == {"type": "text", "text": FINAL_TURN_NOTE}
    assert "tool budget exhausted" in inv.guardrail_events
    # toolu_3 was refused by the budget, so the citation that relies on it does not verify.
    assert [c.verified for c in inv.diagnosis.evidence] == [True, False]


def test_fabricated_evidence_gets_the_diagnosis_withheld(load):
    fabricated = [
        {"claim": "the disk filled up", "tool_call_id": "toolu_1", "quote": "No space left on device"}
    ]
    client = FakeClient(
        response(tool_use("toolu_1", "get_run_overview")),
        response(text(final_answer(category="infra.compute_failure", evidence=fabricated)), stop="end_turn"),
    )
    inv = ClaudeInvestigator(client=client).investigate(*load("INC-H01"))
    assert inv.diagnosis.status == "abstained" and inv.diagnosis.category is None
    assert "diagnosis withheld: no verified evidence" in inv.guardrail_events


def test_refusal_becomes_an_abstention(load):
    refusal = response(stop="refusal")
    refusal.stop_details = SimpleNamespace(category="cyber", explanation="")
    inv = ClaudeInvestigator(client=FakeClient(refusal)).investigate(*load("INC-H01"))
    assert inv.diagnosis.status == "abstained" and "declined" in inv.diagnosis.abstain_reason


def test_fallback_model_usage_is_recorded(load):
    client = FakeClient(
        response(tool_use("toolu_2", "list_failed_checks", include_warnings=False), model="claude-opus-4-8"),
        response(
            tool_use("toolu_3", "get_downstream_impact", node="cms_geo_variation"), model="claude-opus-4-8"
        ),
        response(text(final_answer()), stop="end_turn", model="claude-opus-4-8"),
    )
    inv = ClaudeInvestigator(client=client).investigate(*load("INC-H01"))
    assert any("fallback model claude-opus-4-8" in e for e in inv.guardrail_events)
    assert abs(inv.usage.cost_usd - 3 * (1000 * 5 + 200 * 25) / 1e6) < 1e-9


def test_without_fallbacks_the_standard_endpoint_is_used(load):
    client = FakeClient(
        response(text(final_answer(status="abstained", category="none", evidence=[])), stop="end_turn")
    )
    ClaudeInvestigator(client=client, fallbacks=False).investigate(*load("INC-H01"))
    assert "betas" not in client.requests[0] and "fallbacks" not in client.requests[0]
