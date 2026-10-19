"""The Claude investigator: an agentic tool-use loop over the read-only tools (docs/adr/0005).

The loop is written by hand rather than with the SDK's tool runner because the harness needs per-call
control that sits outside the model: a tool-call budget, an evidence ledger keyed by tool_use id for the
grounding check, a forced final turn, refusal handling, and a span per model turn and per tool call.

Request shape:
  * model `claude-opus-5-5` by default with adaptive thinking (its default) and an explicit effort level;
  * strict tool schemas, and the final answer constrained by a JSON schema (`output_config.format`);
  * automatic prompt caching (`cache_control`), so the static system prompt, tools, and each turn's prefix
    are read from cache on the next turn;
  * server-side refusal fallback (`fallbacks="default"`), so a safety-classifier decline is retried on the
    model Anthropic recommends instead of ending the investigation.
"""

from __future__ import annotations

import json
import time
from typing import Any

from drc.agents.base import finalize
from drc.agents.prompts import DIAGNOSIS_SCHEMA, SYSTEM_PROMPT, incident_message
from drc.models import Catalog, Citation, Diagnosis, IncidentBundle, Investigation, Proposal, Usage
from drc.pricing import add_usage
from drc.tools import DEFAULT_BUDGET, TOOL_SPECS, ToolRegistry
from drc.tracing import Tracer

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FINAL_TURN_NOTE = (
    "You have reached the investigation limit. Do not call more tools. Reply now with your final JSON "
    "diagnosis based on the evidence gathered so far, abstaining if it is not sufficient."
)


class ClaudeInvestigator:
    name = "claude"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        effort: str = "high",
        budget: int = DEFAULT_BUDGET,
        fallbacks: bool = True,
        client: Any = None,
    ):
        self.model = model
        self.effort = effort
        self.budget = budget
        self.fallbacks = fallbacks
        self.max_turns = budget + 4
        self._client = client
        self.tools = [{**spec, "strict": True} for spec in TOOL_SPECS]
        self.config = {"model": model, "effort": effort, "tool_budget": budget, "fallbacks": fallbacks}

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(max_retries=4)
        return self._client

    def _create(self, messages: list[dict[str, Any]], final: bool) -> Any:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "system": SYSTEM_PROMPT,
            "tools": self.tools,
            "messages": messages,
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": DIAGNOSIS_SCHEMA},
            },
            "cache_control": {"type": "ephemeral"},
        }
        if final:
            params["tool_choice"] = {"type": "none"}
        if self.fallbacks:
            return self.client.beta.messages.create(**params, betas=[FALLBACK_BETA], fallbacks="default")
        return self.client.messages.create(**params)

    def investigate(
        self, bundle: IncidentBundle, catalog: Catalog, tracer: Tracer | None = None
    ) -> Investigation:
        tracer = tracer or Tracer()
        registry = ToolRegistry(bundle, catalog, budget=self.budget, tracer=tracer)
        usage = Usage(model=self.model)
        events: list[str] = []
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": incident_message(bundle.incident, self.budget)}
        ]
        diagnosis: Diagnosis | None = None
        t0 = time.perf_counter()
        with tracer.span(
            "investigation",
            **{"drc.investigator": self.name, "drc.incident_id": bundle.incident.incident_id, **self.config},
        ):
            for turn in range(self.max_turns):
                final = turn == self.max_turns - 1 or len(registry.calls) >= self.budget
                if final and turn > 0:
                    messages[-1]["content"].append({"type": "text", "text": FINAL_TURN_NOTE})
                with tracer.span(
                    f"chat {self.model}",
                    **{
                        "gen_ai.operation.name": "chat",
                        "gen_ai.system": "anthropic",
                        "gen_ai.request.model": self.model,
                        "drc.turn": turn,
                    },
                ) as span:
                    response = self._create(messages, final=final and turn > 0)
                    add_usage(usage, response.model, response.usage)
                    span.set(
                        **{
                            "gen_ai.response.model": response.model,
                            "gen_ai.response.finish_reasons": [response.stop_reason],
                            "gen_ai.usage.input_tokens": response.usage.input_tokens,
                            "gen_ai.usage.output_tokens": response.usage.output_tokens,
                            "gen_ai.usage.cache_read_input_tokens": getattr(
                                response.usage, "cache_read_input_tokens", 0
                            ),
                            "gen_ai.usage.cache_creation_input_tokens": getattr(
                                response.usage, "cache_creation_input_tokens", 0
                            ),
                            "drc.request_id": getattr(response, "_request_id", None),
                        }
                    )
                if response.model != self.model:
                    events.append(f"turn {turn}: served by fallback model {response.model}")
                if response.stop_reason == "refusal":
                    details = getattr(response, "stop_details", None)
                    events.append(f"model declined: {getattr(details, 'category', None)}")
                    diagnosis = _abstain(
                        f"the model declined to continue ({getattr(details, 'category', 'unspecified')})"
                    )
                    break
                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason == "pause_turn":
                    continue
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason == "tool_use" and tool_uses:
                    results = []
                    for block in tool_uses:
                        record = registry.call(block.name, dict(block.input), api_id=block.id)
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": f"call_id: {record.call_id}\n{record.output}",
                                "is_error": record.is_error,
                            }
                        )
                    messages.append({"role": "user", "content": results})
                    continue
                if response.stop_reason == "max_tokens":
                    events.append("final answer truncated at max_tokens")
                    diagnosis = _abstain("the final answer was truncated")
                    break
                text = "".join(b.text for b in response.content if b.type == "text")
                try:
                    diagnosis = parse_diagnosis(text)
                except (ValueError, TypeError) as exc:
                    events.append(f"unparseable final answer: {exc}")
                    diagnosis = _abstain("the final answer did not match the diagnosis schema")
                break
            else:
                events.append("turn limit reached without a final answer")
                diagnosis = _abstain("the investigation hit its turn limit")
            return finalize(
                self.name, bundle, registry, diagnosis, usage, time.perf_counter() - t0, tracer, events
            )


def _abstain(reason: str) -> Diagnosis:
    return Diagnosis(
        status="abstained", summary="Investigation did not complete.", confidence=0.0, abstain_reason=reason
    )


def parse_diagnosis(text: str) -> Diagnosis:
    data = json.loads(text)
    category = data.get("category")
    return Diagnosis(
        status=data["status"],
        category=None if category in (None, "", "none") else category,
        summary=data.get("summary", ""),
        source=data.get("source") or None,
        columns=data.get("columns") or [],
        consumer_impact=data.get("consumer_impact", "unknown"),
        confidence=min(1.0, max(0.0, float(data.get("confidence", 0.0)))),
        evidence=[Citation(**e) for e in data.get("evidence", [])],
        remediation=[Proposal(**p) for p in data.get("remediation", [])],
        open_questions=data.get("open_questions") or [],
        abstain_reason=data.get("abstain_reason") or None,
    )
