"""The investigator's tool surface: ten read-only tools over one incident's evidence.

Design rules (docs/adr/0001, docs/threat-model.md):
  * Read-only by construction. Tools read an `IncidentBundle` and a `Catalog` held in memory; there is no
    code path from a tool to the pipeline, its storage, or the network.
  * Closed allowlist. A call to any other tool name is refused and recorded as a guardrail event.
  * Bounded. Each result is capped in size, and each investigation has a tool-call budget.
  * Recorded. Every call gets an id, and its exact output is kept so citations can be verified later.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from drc.models import Catalog, IncidentBundle, ToolCall
from drc.tracing import Tracer

MAX_OUTPUT_CHARS = 9000
DEFAULT_BUDGET = 24


def _schema(properties: dict[str, Any] | None = None) -> dict[str, Any]:
    properties = properties or {}
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SOURCE = {"type": "string", "description": "Source (feed) name, as listed by get_run_overview."}
COLUMNS = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Column or field names. Pass an empty list for an overview.",
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "get_run_overview",
        "description": "Status of the incident run: the alert, run status and message, every step with its "
        "status, duration and details, the sources involved, and which warnings already fired on the previous "
        "published run. Start here.",
        "input_schema": _schema(),
    },
    {
        "name": "list_failed_checks",
        "description": "Quality checks in this run that did not pass (fail or error, and optionally warn), "
        "with observed vs expected values and messages. Skipped checks are counted, not listed.",
        "input_schema": _schema({"include_warnings": {"type": "boolean"}}),
    },
    {
        "name": "get_check_details",
        "description": "Full detail for one check: offending sample values, failing rows returned by an audit "
        "query and the query itself, or the source records named in an error. Use the check_name from "
        "list_failed_checks; pass its source when the check is source-specific, otherwise an empty string.",
        "input_schema": _schema({"check_name": {"type": "string"}, "source": {"type": "string"}}),
    },
    {
        "name": "get_data_contract",
        "description": "The data contract (or code-defined quality gates) for a source: policy thresholds, "
        "grain, sentinels, and per-column rules.",
        "input_schema": _schema({"source": SOURCE, "columns": COLUMNS}),
    },
    {
        "name": "compare_schema",
        "description": "Compare the structure of the delivery read by this run with the previous accepted one: "
        "columns or fields added and removed, likely renames, and file-level facts (size, parse errors).",
        "input_schema": _schema({"source": SOURCE}),
    },
    {
        "name": "profile_columns",
        "description": "Column profiles of this run's delivery next to the previous accepted delivery: counts, "
        "nulls, sentinels, distinct values, parse failures, min/median/mean/max, pattern violations, examples. "
        "With an empty column list, returns the columns whose profile changed most.",
        "input_schema": _schema({"source": SOURCE, "columns": COLUMNS}),
    },
    {
        "name": "get_release_history",
        "description": "Recent deliveries of a source with row counts, contract status, and publish state.",
        "input_schema": _schema({"source": SOURCE}),
    },
    {
        "name": "get_downstream_impact",
        "description": "Lineage from a node (a source, model, table, or check name) to everything downstream "
        "of it, the consumers that read those assets, and what consumers are being served right now.",
        "input_schema": _schema({"node": {"type": "string"}}),
    },
    {
        "name": "search_runbook",
        "description": "Search the platform's runbook and design documentation. Returns the best-matching sections.",
        "input_schema": _schema({"query": {"type": "string"}}),
    },
    {
        "name": "get_logs",
        "description": "Log excerpts recorded for the run. Pass an empty string to list what is available, "
        "or a log name.",
        "input_schema": _schema({"name": {"type": "string"}}),
    },
]
TOOL_NAMES = frozenset(t["name"] for t in TOOL_SPECS)


class ToolError(ValueError):
    pass


def _dump(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + f" ... [truncated: {len(text) - MAX_OUTPUT_CHARS} more characters]"
    return text


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class ToolRegistry:
    bundle: IncidentBundle
    catalog: Catalog
    budget: int = DEFAULT_BUDGET
    tracer: Tracer | None = None
    calls: list[ToolCall] = field(default_factory=list)
    guardrail_events: list[str] = field(default_factory=list)
    _counter: int = 0

    @property
    def evidence(self):
        return self.bundle.evidence

    # ---- dispatch -----------------------------------------------------------------------------------
    def call(self, name: str, arguments: dict[str, Any] | None, call_id: str | None = None) -> ToolCall:
        self._counter += 1
        call_id = call_id or f"call_{self._counter:02d}"
        arguments = arguments or {}
        tracer = self.tracer or Tracer()
        with tracer.span(
            f"execute_tool {name}",
            **{
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": name,
                "gen_ai.tool.call.id": call_id,
            },
        ) as span:
            record = self._execute(name, arguments, call_id)
            span.set(**{"drc.tool.is_error": record.is_error, "drc.tool.output_chars": len(record.output)})
        return record

    def _execute(self, name: str, arguments: dict[str, Any], call_id: str) -> ToolCall:
        t0 = time.perf_counter()
        is_error = False
        if name not in TOOL_NAMES:
            self.guardrail_events.append(f"refused unknown tool '{name}'")
            output, is_error = (
                f"Error: '{name}' is not an available tool. Tools are read-only: {sorted(TOOL_NAMES)}",
                True,
            )
        elif len(self.calls) >= self.budget:
            self.guardrail_events.append("tool budget exhausted")
            output, is_error = (
                "Error: tool-call budget exhausted. Submit your diagnosis with the evidence gathered.",
                True,
            )
        else:
            try:
                output = _dump(getattr(self, f"_{name}")(**arguments))
            except (ToolError, TypeError) as exc:
                output, is_error = f"Error: {exc}", True
        record = ToolCall(
            call_id=call_id,
            name=name,
            arguments=arguments,
            output=output,
            is_error=is_error,
            duration_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
        self.calls.append(record)
        return record

    def _source(self, source: str) -> str:
        if source not in self.catalog.sources:
            raise ToolError(f"unknown source '{source}'. Sources: {self.catalog.sources}")
        return source

    # ---- tools ----------------------------------------------------------------------------------------
    def _get_run_overview(self) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        for c in self.evidence.checks:
            statuses[c["status"]] = statuses.get(c["status"], 0) + 1
        return {
            "incident": self.bundle.incident.model_dump(),
            "sources": self.catalog.sources,
            "run": self.evidence.run,
            "check_counts_by_status": statuses,
        }

    def _list_failed_checks(self, include_warnings: bool) -> dict[str, Any]:
        wanted = {"fail", "error"} | ({"warn"} if include_warnings else set())
        persisting = set(self.evidence.run.get("warnings_on_previous_published_run") or [])
        rows = []
        for c in self.evidence.checks:
            if c["status"] in wanted:
                row = {
                    k: c.get(k)
                    for k in ("layer", "source", "check_name", "status", "observed", "expected", "message")
                }
                if c["status"] == "warn":
                    row["also_warned_on_previous_published_run"] = c["check_name"] in persisting
                rows.append(row)
        skipped = sum(
            1 for c in self.evidence.checks if c["status"] in ("skipped", "not_run", "upstream_failed")
        )
        return {"checks": rows, "skipped_or_not_run": skipped}

    def _get_check_details(self, check_name: str, source: str | None) -> dict[str, Any]:
        details = self.evidence.check_details
        keys = [f"{source}:{check_name}"] if source else []
        keys += [check_name] + [k for k in details if k.endswith(f":{check_name}")]
        for key in keys:
            if key in details:
                return {"key": key, **details[key]}
        raise ToolError(f"no recorded detail for '{check_name}'. Recorded details: {sorted(details)}")

    def _get_data_contract(self, source: str, columns: list[str]) -> dict[str, Any]:
        contract = self.catalog.contracts.get(self._source(source))
        if contract is None:
            raise ToolError(f"no contract recorded for {source}")
        out = {k: v for k, v in contract.items() if k != "columns"}
        if "columns" in contract:
            specs = contract["columns"]
            if columns:
                out["columns"] = {c: specs.get(c, "not in contract") for c in columns}
            else:
                out["columns"] = specs
        return out

    def _compare_schema(self, source: str) -> dict[str, Any]:
        info = self.evidence.schemas.get(self._source(source))
        if info is None:
            raise ToolError(f"no schema recorded for {source} in this run")
        current, previous = info.get("current_header"), info.get("previous_header")
        out = {k: v for k, v in info.items() if k not in ("current_header", "previous_header")}
        if current is None or previous is None:
            out["comparison"] = "not available: the current or previous structure could not be read"
            out["current_columns"] = len(current) if current else None
            out["previous_columns"] = len(previous) if previous else None
            return out
        added = [c for c in current if c not in previous]
        removed = [c for c in previous if c not in current]
        renames = []
        for old in removed:
            match = difflib.get_close_matches(old, added, n=1, cutoff=0.75)
            if match:
                ratio = difflib.SequenceMatcher(None, old, match[0]).ratio()
                renames.append({"removed": old, "added": match[0], "similarity": round(ratio, 3)})
        out.update(
            current_columns=len(current),
            previous_columns=len(previous),
            added=added,
            removed=removed,
            likely_renames=renames,
        )
        return out

    def _profile_columns(self, source: str, columns: list[str]) -> dict[str, Any]:
        info = self.evidence.profiles.get(self._source(source))
        if not info:
            state = (self.evidence.schemas.get(source) or {}).get("release_state", "no delivery in this run")
            return {"source": source, "profile": f"not available: {state}"}
        current, previous = info.get("current") or {}, info.get("previous") or {}
        head = {
            "source": source,
            "current_release": info.get("current_release"),
            "previous_release": info.get("previous_release"),
            "rows": {"current": current.get("_rows"), "previous": previous.get("_rows")},
        }
        if "_error" in current:
            head["current_profile_error"] = current["_error"]
        if "_resource_types" in current or "_resource_types" in previous:
            head["resource_types"] = {
                "current": current.get("_resource_types"),
                "previous": previous.get("_resource_types"),
            }
        names = [c for c in current if not c.startswith("_")] + [
            c for c in previous if not c.startswith("_") and c not in current
        ]
        if not columns:
            ranked = sorted(names, key=lambda c: -_change_score(current.get(c), previous.get(c)))
            head["columns_with_notable_changes"] = [
                {"column": c, "current": current.get(c), "previous": previous.get(c)}
                for c in ranked[:6]
                if _change_score(current.get(c), previous.get(c)) > 1e-9
            ]
            head["profiled_columns"] = len(names)
            return head
        head["columns"] = {
            c: {"current": current.get(c, "not profiled"), "previous": previous.get(c, "not profiled")}
            for c in columns
        }
        return head

    def _get_release_history(self, source: str) -> dict[str, Any]:
        return {"source": source, "releases": self.evidence.releases.get(self._source(source), [])[-8:]}

    def _get_downstream_impact(self, node: str) -> dict[str, Any]:
        lineage = self.catalog.lineage or {}
        nodes, tests = lineage.get("nodes", {}), lineage.get("tests", {})
        children: dict[str, list[str]] = {}
        for parent, child in lineage.get("edges", []):
            children.setdefault(parent, []).append(child)
        start = [node]
        if node in self.catalog.sources:
            start = [n for n in nodes if n == node or n.endswith(f".{node}")]
        reads: list[str] = []
        if node in tests:
            reads = tests[node]
            start = reads
        elif not any(s in nodes for s in start):
            raise ToolError(
                f"unknown lineage node '{node}'. Known: sources {self.catalog.sources}, "
                f"{len(nodes)} assets, {len(tests)} checks"
            )
        seen, queue = set(start), deque(start)
        while queue:
            for child in children.get(queue.popleft(), []):
                if child not in seen:
                    seen.add(child)
                    queue.append(child)
        downstream = sorted(seen - set(start)) if node not in tests else sorted(seen)
        names = {d.split(".")[-1] for d in downstream} | set(downstream)
        consumers = [
            c
            for c in self.catalog.consumers
            if any(r in names or r.split(".")[-1] in names for r in c["reads"])
        ]
        return {
            "node": node,
            "check_reads": reads or None,
            "downstream": [{"asset": d, "layer": nodes.get(d, {}).get("layer")} for d in downstream],
            "consumers": consumers,
            "currently_served": self.evidence.publish_state,
        }

    def _search_runbook(self, query: str) -> dict[str, Any]:
        docs = self.catalog.knowledge
        if not docs:
            return {"results": [], "note": "no runbook recorded for this platform"}
        terms = set(_tokens(query))
        n = len(docs)
        df = {t: sum(1 for d in docs if t in set(_tokens(d["section"] + " " + d["text"]))) for t in terms}
        scored = []
        for d in docs:
            words = _tokens(d["section"] + " " + d["section"] + " " + d["text"])
            if not words:
                continue
            score = sum(
                words.count(t) / (words.count(t) + 1.2) * math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                for t in terms
                if df[t]
            )
            if score > 0:
                scored.append((score, d))
        scored.sort(key=lambda s: -s[0])
        return {
            "results": [{"doc": d["doc"], "section": d["section"], "text": d["text"]} for _, d in scored[:3]]
        }

    def _get_logs(self, name: str | None) -> dict[str, Any]:
        logs = self.evidence.logs
        if not name:
            return {"available": sorted(logs)}
        if name not in logs:
            raise ToolError(f"no log named '{name}'. Available: {sorted(logs)}")
        return {"name": name, "text": "\n".join(logs[name].splitlines()[-60:])}


def _change_score(cur: Any, prev: Any) -> float:
    """How much a column's profile moved between deliveries (0 = no visible change)."""
    if not isinstance(cur, dict) or not isinstance(prev, dict):
        return 5.0 if (cur is None) != (prev is None) else 0.0
    if cur.get("present") != prev.get("present"):
        return 5.0
    score = 0.0
    for key in ("non_numeric", "pattern_violations", "unresolved_references", "without_timezone"):
        if (cur.get(key) or 0) != (prev.get(key) or 0):
            score += 3.0
    for key in ("mean", "max", "median"):
        a, b = cur.get(key), prev.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a > 0 and b > 0:
            score += min(abs(math.log10(a / b)), 3.0)
    for key in ("nulls", "missing", "distinct", "count"):
        a, b = cur.get(key) or 0, prev.get(key) or 0
        if max(a, b):
            score += abs(a - b) / max(a, b)
    if cur.get("sentinels") != prev.get("sentinels"):
        a = sum((cur.get("sentinels") or {}).values())
        b = sum((prev.get("sentinels") or {}).values())
        score += abs(a - b) / max(a, b, 1)
    if cur.get("values") is not None and cur.get("values") != prev.get("values"):
        score += 1.0
    return score
