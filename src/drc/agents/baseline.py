"""A deterministic playbook investigator: the control the AI agent has to beat (docs/adr/0004).

It uses the same read-only tools as the agent and cites their output the same way, so both are scored
by identical rules. Its rules encode what an experienced engineer would automate from hcip's check
vocabulary, plus a few platform-independent infrastructure signatures (missing file, locked resource).
It has no rules for the clinical ETL's quality-gate messages: that pipeline is held out to measure how
well each investigator transfers to a newly onboarded platform. When no rule fires, it abstains.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from typing import Any

from drc.agents.base import finalize
from drc.models import Catalog, Citation, Diagnosis, IncidentBundle, Investigation, Proposal, ToolCall, Usage
from drc.tools import ToolRegistry
from drc.tracing import Tracer

REMEDIATION: dict[str, list[tuple[str, str]]] = {
    "schema.required_column_missing": [("request_corrected_delivery", "high")],
    "schema.column_renamed": [("amend_data_contract", "medium"), ("update_transformation", "medium")],
    "schema.additive_drift": [("monitor_no_action", "low"), ("amend_data_contract", "low")],
    "volume.truncated_delivery": [("request_corrected_delivery", "medium"), ("rerun_pipeline", "low")],
    "volume.empty_delivery": [("request_corrected_delivery", "medium"), ("rerun_pipeline", "low")],
    "integrity.duplicate_records": [("request_corrected_delivery", "medium")],
    "values.type_format_drift": [
        ("request_corrected_delivery", "medium"),
        ("review_quarantined_rows", "low"),
    ],
    "values.identifier_corruption": [("request_corrected_delivery", "medium")],
    "values.domain_violation": [("correct_source_records", "medium")],
    "values.suppression_policy_change": [("amend_data_contract", "medium")],
    "values.cross_field_inconsistency": [("review_quarantined_rows", "low")],
    "semantic.aggregate_reconciliation_break": [("request_corrected_delivery", "medium")],
    "semantic.unit_change": [("request_corrected_delivery", "medium"), ("amend_data_contract", "medium")],
    "referential.orphan_reference": [("correct_source_records", "medium")],
    "referential.cross_entity_mismatch": [("correct_source_records", "medium")],
    "infra.source_unavailable": [("escalate_to_platform_oncall", "low"), ("rerun_pipeline", "low")],
    "infra.resource_contention": [("escalate_to_platform_oncall", "low"), ("rerun_pipeline", "low")],
    "infra.compute_failure": [("escalate_to_platform_oncall", "low")],
}
INFRA_SIGNATURES = [
    (
        re.compile(r"not found|no such file|unreachable|connection (refused|error)", re.I),
        "infra.source_unavailable",
    ),
    (
        re.compile(r"database is locked|being used by another process|permission denied", re.I),
        "infra.resource_contention",
    ),
]


class _Finding(Exception):
    """Raised by a rule once it has reached a diagnosis."""

    def __init__(self, category: str, summary: str, source: str | None, columns: list[str]):
        super().__init__(category)
        self.category, self.summary, self.source, self.columns = category, summary, source, columns


class BaselineInvestigator:
    name = "baseline"

    def investigate(
        self, bundle: IncidentBundle, catalog: Catalog, tracer: Tracer | None = None
    ) -> Investigation:
        tracer = tracer or Tracer()
        t0 = time.perf_counter()
        with tracer.span(
            "investigation", **{"drc.investigator": self.name, "drc.incident_id": bundle.incident.incident_id}
        ):
            run = _Run(ToolRegistry(bundle, catalog, tracer=tracer))
            diagnosis = run.diagnose()
            return finalize(
                self.name, bundle, run.registry, diagnosis, Usage(), time.perf_counter() - t0, tracer
            )


class _Run:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.citations: list[Citation] = []

    # ---- helpers ----------------------------------------------------------------------------------
    def call(self, name: str, **arguments: Any) -> tuple[ToolCall, Any]:
        record = self.registry.call(name, arguments)
        return record, (None if record.is_error else json.loads(record.output.split(" ... [truncated")[0]))

    def cite(self, record: ToolCall, quote: Any, claim: str) -> None:
        text = quote if isinstance(quote, str) else json.dumps(quote, ensure_ascii=False)
        self.citations.append(Citation(claim=claim, tool_call_id=record.call_id, quote=text[:200]))

    def changed_source(self) -> str | None:
        for source in self.registry.catalog.sources:
            record, schema = self.call("compare_schema", source=source)
            if schema and schema.get("release_state", "").startswith("new"):
                self.cite(record, schema["release_state"], f"{source} delivered new data in this run")
                return source
        return None

    def top_changed_columns(self, source: str, n: int = 2) -> tuple[ToolCall | None, list[dict[str, Any]]]:
        record, profile = self.call("profile_columns", source=source, columns=[])
        return record, (profile or {}).get("columns_with_notable_changes", [])[:n]

    # ---- rules --------------------------------------------------------------------------------------
    def diagnose(self) -> Diagnosis:
        overview_call, overview = self.call("get_run_overview")
        checks_call, failed = self.call("list_failed_checks", include_warnings=True)
        checks = failed["checks"]
        candidates = [c for c in checks if c["status"] in ("fail", "error")] + [
            c for c in checks if c["status"] == "warn" and not c.get("also_warned_on_previous_published_run")
        ]
        rules: dict[str, Callable[[dict[str, Any]], None]] = {
            "header.required_columns": self.rule_required_columns,
            "volume.row_count": self.rule_volume,
            "volume.change_vs_previous_release": self.rule_volume,
            "grain.unique": self.rule_grain,
            "values.row_error_budget": self.rule_value_budget,
            "values.suppression_rate": self.rule_suppression,
            "values.suppression_shift_vs_previous_release": self.rule_suppression,
            "header.drift_vs_previous_release": self.rule_drift,
        }
        try:
            for check in candidates:
                mark = len(self.citations)
                self.cite(
                    checks_call,
                    check["message"] or check["check_name"],
                    f"{check['check_name']} reported {check['status']}",
                )
                name = check["check_name"]
                if name in rules:
                    rules[name](check)
                elif "reconcile" in name:
                    self.rule_reconciliation(check)
                elif "per_capita" in name:
                    self.rule_unit(check)
                elif "quarantine" in name:
                    self.rule_quarantine(check)
                del self.citations[mark:]  # the check did not lead anywhere; do not cite it
            self.rule_infrastructure(overview_call, overview)
        except _Finding as found:
            return self.diagnosed(found)
        return self.abstain(overview, checks)

    def rule_required_columns(self, check: dict[str, Any]) -> None:
        record, schema = self.call("compare_schema", source=check["source"])
        renames = schema.get("likely_renames") or []
        if renames:
            r = renames[0]
            self.cite(record, r["added"], f"{r['removed']} disappeared and {r['added']} appeared")
            raise _Finding(
                "schema.column_renamed",
                f"{check['source']} renamed {r['removed']} to {r['added']}; the contract requires {r['removed']}.",
                check["source"],
                [r["removed"], r["added"]],
            )
        missing = schema.get("removed") or check.get("observed") or []
        raise _Finding(
            "schema.required_column_missing",
            f"{check['source']} no longer delivers required column(s) {', '.join(missing)}.",
            check["source"],
            list(missing),
        )

    def rule_volume(self, check: dict[str, Any]) -> None:
        record, profile = self.call("profile_columns", source=check["source"], columns=[])
        rows = (profile or {}).get("rows", {})
        current, previous = rows.get("current"), rows.get("previous")
        if current == 0:
            self.cite(record, '"current": 0', "the delivery has no data rows")
            raise _Finding(
                "volume.empty_delivery",
                f"{check['source']} delivered a file with a header and no rows.",
                check["source"],
                [],
            )
        if current is not None and previous and current < previous:
            self.cite(record, f'"current": {current}', f"the delivery has {current} rows")
            self.cite(
                record, f'"previous": {previous}', f"the previous accepted delivery had {previous} rows"
            )
            raise _Finding(
                "volume.truncated_delivery",
                f"{check['source']} delivered {current} rows against {previous} previously "
                f"({1 - current / previous:.0%} fewer): the delivery looks truncated.",
                check["source"],
                [],
            )

    def rule_grain(self, check: dict[str, Any]) -> None:
        raise _Finding(
            "integrity.duplicate_records",
            f"{check['source']} delivered duplicate rows for its grain ({check['message']}).",
            check["source"],
            [],
        )

    def rule_value_budget(self, check: dict[str, Any]) -> None:
        record, detail = self.call(
            "get_check_details", check_name=check["check_name"], source=check["source"]
        )
        violations = sorted((detail or {}).get("samples") or [], key=lambda v: -v.get("rows", 0))
        if not violations:
            return
        top = violations[0]
        column, rule, samples = top["column"], top["rule"], [str(s) for s in top.get("samples", [])]
        self.cite(record, column, f"violations concentrate in {column}")
        if samples:
            self.cite(record, samples[0], f"offending values look like {samples[0]!r}")
        if rule == "pattern":
            _, contract = self.call("get_data_contract", source=check["source"], columns=[column])
            pattern = ((contract or {}).get("columns", {}).get(column) or {}).get("pattern")
            if (
                pattern
                and samples
                and all(
                    s.isdigit()
                    and any(re.fullmatch(pattern, s.zfill(n)) for n in range(len(s) + 1, len(s) + 3))
                    for s in samples
                )
            ):
                raise _Finding(
                    "values.identifier_corruption",
                    f"{column} values lost their leading zeros (e.g. {samples[0]!r}).",
                    check["source"],
                    [column],
                )
            return
        if rule.startswith("type_"):
            raise _Finding(
                "values.type_format_drift",
                f"{column} arrives in a non-numeric format (e.g. {samples[0]!r}); {top['rows']} rows affected.",
                check["source"],
                [column],
            )
        if rule in ("min", "max", "accepted_values"):
            raise _Finding(
                "values.domain_violation",
                f"{column} has values outside its allowed {rule}.",
                check["source"],
                [column],
            )

    def rule_suppression(self, check: dict[str, Any]) -> None:
        record, contract = self.call("get_data_contract", source=check["source"], columns=[])
        column = ((contract or {}).get("policy", {}).get("suppression") or {}).get("column")
        if column:
            self.cite(record, column, f"the suppression policy is measured on {column}")
        raise _Finding(
            "values.suppression_policy_change",
            f"{check['source']} suppressed far more values than before ({check['message']}).",
            check["source"],
            [column] if column else [],
        )

    def rule_drift(self, check: dict[str, Any]) -> None:
        record, schema = self.call("compare_schema", source=check["source"])
        added, removed = schema.get("added") or [], schema.get("removed") or []
        if added and not removed:
            self.cite(record, added[0][:120], "a new column appeared")
            raise _Finding(
                "schema.additive_drift",
                f"{check['source']} added {len(added)} uncontracted column(s); contracted columns are unchanged.",
                check["source"],
                added,
            )

    def rule_reconciliation(self, check: dict[str, Any]) -> None:
        detail_call, detail = self.call("get_check_details", check_name=check["check_name"], source="")
        rows = (detail or {}).get("failing_rows") or []
        if rows:
            self.cite(
                detail_call,
                json.dumps(rows[0], ensure_ascii=False)[:120],
                "the audit query returned an out-of-bounds total",
            )
        source = self.changed_source()
        columns: list[str] = []
        if source:
            record, top = self.top_changed_columns(source, 1)
            if top and record:
                columns = [top[0]["column"]]
                self.cite(
                    record, top[0]["column"], f"{columns[0]} changed most against the previous delivery"
                )
        raise _Finding(
            "semantic.aggregate_reconciliation_break",
            "Detail rows no longer reconcile to their published totals"
            + (f"; the change is concentrated in {source}.{columns[0]}." if columns else "."),
            source,
            columns,
        )

    def rule_unit(self, check: dict[str, Any]) -> None:
        source = self.changed_source()
        if not source:
            return
        record, top = self.top_changed_columns(source, 3)
        for column in top:
            cur, prev = column.get("current") or {}, column.get("previous") or {}
            a, b = cur.get("mean"), prev.get("mean")
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a > 0 and b > 0:
                exponent = math.log10(a / b)
                if abs(exponent) >= 1 and abs(exponent - round(exponent)) < 0.05:
                    self.cite(record, f'"mean": {a}', f"{column['column']} mean is now {a}")
                    self.cite(record, f'"mean": {b}', f"{column['column']} mean was {b}")
                    raise _Finding(
                        "semantic.unit_change",
                        f"{column['column']} shifted by a factor of 10^{round(exponent)}: republished in different units.",
                        source,
                        [column["column"]],
                    )

    def rule_quarantine(self, check: dict[str, Any]) -> None:
        record, detail = self.call("get_check_details", check_name=check["check_name"], source="")
        reasons = {
            e for row in (detail or {}).get("failing_rows") or [] for e in (row.get("dq_errors") or [])
        }
        if any("confidence interval" in r for r in reasons):
            self.cite(
                record,
                "confidence interval does not bracket value",
                "quarantined rows have inverted intervals",
            )
            source = self.changed_source()
            _, top = self.top_changed_columns(source, 2) if source else (None, [])
            raise _Finding(
                "values.cross_field_inconsistency",
                "Rows were quarantined because their confidence interval does not bracket the estimate.",
                source,
                [t["column"] for t in top],
            )

    def rule_infrastructure(self, record: ToolCall, overview: dict[str, Any]) -> None:
        message = " ".join(
            [overview["incident"]["headline"], str(overview["run"].get("message") or "")]
            + [
                str(s.get("detail", {}).get("error", ""))
                for s in overview["run"].get("steps", [])
                if isinstance(s.get("detail"), dict)
            ]
        )
        for pattern, category in INFRA_SIGNATURES:
            match = pattern.search(message)
            if match:
                self.cite(record, match.group(0), f"the run failed with '{match.group(0)}'")
                source = next((s for s in self.registry.catalog.sources if s in message), None)
                raise _Finding(
                    category, f"The run failed on an infrastructure error: '{match.group(0)}'.", source, []
                )

    # ---- outcome --------------------------------------------------------------------------------------
    def impact(self, source: str | None) -> str:
        node = source or self.registry.catalog.sources[0]
        record, impact = self.call("get_downstream_impact", node=node)
        state = (impact or {}).get("currently_served") or {}
        served = state.get("this_run_is_served") or state.get("this_run_loaded")
        key = "this_run_is_served" if "this_run_is_served" in state else "this_run_loaded"
        self.cite(
            record, f'"{key}": {json.dumps(bool(served))}', "whether this run's output reached consumers"
        )
        if not served:
            return "previous_version_served"
        statuses = {c["status"] for c in self.registry.bundle.evidence.checks}
        if "fail" in statuses:
            return "inconsistent_data_served"
        names = " ".join(
            c["check_name"] for c in self.registry.bundle.evidence.checks if c["status"] == "warn"
        )
        return (
            "published_with_quarantine"
            if ("quarantine" in names or "row_error_budget" in names)
            else "published_with_warning"
        )

    def diagnosed(self, found: _Finding) -> Diagnosis:
        target = found.source or self.registry.bundle.incident.pipeline
        return Diagnosis(
            status="diagnosed",
            category=found.category,
            summary=found.summary,
            source=found.source,
            columns=found.columns,
            consumer_impact=self.impact(found.source),
            confidence=0.9,
            evidence=self.citations,
            remediation=[
                Proposal(
                    action_type=a,
                    target=target,
                    description=f"Playbook action for {found.category}.",
                    risk=risk,
                )
                for a, risk in REMEDIATION[found.category]
            ],
        )

    def abstain(self, overview: dict[str, Any], checks: list[dict[str, Any]]) -> Diagnosis:
        impact = self.impact(None)
        return Diagnosis(
            status="abstained",
            summary="No playbook rule matches this incident's evidence.",
            consumer_impact=impact,
            confidence=0.0,
            evidence=self.citations,
            abstain_reason=f"no rule for signal {overview['incident']['signal']} with "
            f"{len(checks)} non-passing check(s); route to a human investigator",
            remediation=[
                Proposal(
                    action_type="escalate_to_platform_oncall",
                    target=self.registry.bundle.incident.pipeline,
                    description="Escalate with the collected evidence.",
                    risk="low",
                )
            ],
        )
