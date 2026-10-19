"""Static demo site: replays recorded investigations of every benchmark incident.

`drc site` writes one self-contained HTML page (hosted on GitHub Pages) from the published evaluation
results, the labels, and the incident bundles. Nothing on the page calls a model: it shows what each
investigator did in a recorded run, tool call by tool call, with the grounding check's verdict on every
citation and the policy's verdict on every proposal. The coverage guardrail is replayed over runs recorded
before it existed (drc.coverage), so every run shows its verdict. Rendering lives in `templates/site.html`;
this module only gathers and serializes data.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from drc import coverage
from drc.lab import store
from drc.models import IncidentBundle, Investigation
from drc.taxonomy import CATEGORIES, REMEDIATION_CATALOG

REPO_URL = "https://github.com/KilgoreC1024/healthcare-data-reliability-copilot"
PLACEHOLDER = "/*__DRC_DATA__*/"
INVESTIGATORS = ("claude", "baseline")
# Per-incident scores from the evaluation harness; the page totals them, so its numbers are the harness's.
CASE_FIELDS = (
    "outcome",
    "localized",
    "impact_correct",
    "remediation_relevant",
    "forbidden_actions",
    "policy_rejections",
    "injection_resisted",
    "citations",
    "citations_verified",
)


def _load_results(results_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Every published run per investigator: `<name>.json`, then any `<name>-<suffix>.json` (for example one
    benchmark release run on its own). A later file wins for an incident that appears in more than one."""
    runs = {}
    for name in INVESTIGATORS:
        paths = [results_dir / f"{name}.json"] + sorted(results_dir.glob(f"{name}-*.json"))
        loaded = [json.loads(p.read_text(encoding="utf-8")) for p in paths if p.is_file()]
        if loaded:
            runs[name] = loaded
    return runs


def _investigation(inv: dict[str, Any], case: dict[str, Any], bundle: IncidentBundle) -> dict[str, Any]:
    usage = inv.get("usage") or {}
    replayed = coverage.replay(Investigation.model_validate(inv), bundle)
    return {
        **{k: case.get(k) for k in CASE_FIELDS},
        "diagnosis": replayed.diagnosis.model_dump(mode="json"),
        # True when the run predates the coverage guardrail and its verdict comes from the replay.
        "review_replayed": "needs_review" not in inv["diagnosis"],
        "tool_calls": [
            {k: tc[k] for k in ("call_id", "name", "arguments", "output", "is_error")}
            for tc in inv["tool_calls"]
        ],
        "guardrail_events": replayed.guardrail_events,
        "usage": {k: usage.get(k) for k in ("cost_usd", "turns", "input_tokens", "output_tokens")},
        "latency_s": inv.get("latency_s"),
    }


def payload(root: Path | None = None, results_dir: Path | None = None) -> dict[str, Any]:
    root = root or store.benchmark_root()
    results_dir = results_dir or root.parent / "eval" / "results"
    labels = store.load_labels(root)
    runs = _load_results(results_dir)
    by_run = {
        name: (
            {c["incident_id"]: c for run in run_list for c in run["cases"]},
            {i["incident"]["incident_id"]: i for run in run_list for i in run["investigations"]},
        )
        for name, run_list in runs.items()
    }
    incidents = []
    for incident_id in store.list_incidents(root):
        label = labels[incident_id]
        bundle = store.load_bundle(incident_id, root)
        incident = bundle.incident
        results = {}
        for name, (cases, investigations) in by_run.items():
            if incident_id in investigations:
                results[name] = _investigation(investigations[incident_id], cases[incident_id], bundle)
        incidents.append(
            {
                "id": incident_id,
                "release": label.get("release", 1),
                "platform": incident.platform,
                "signal": incident.signal,
                "failed_stage": incident.failed_stage,
                "headline": incident.headline,
                "label": {k: v for k, v in label.items() if k != "scenario"},
                "results": results,
            }
        )

    def release_of(run: dict[str, Any]) -> int | None:
        """The run's benchmark release: recorded by `drc eval --release`, or implied when every incident it
        covered belongs to one release."""
        releases = {
            labels[c["incident_id"]].get("release", 1) for c in run["cases"] if c["incident_id"] in labels
        }
        return run.get("release") or (releases.pop() if len(releases) == 1 else None)

    runs_info = {
        name: [
            {
                "config": run.get("config") or {},
                "started_at": run.get("started_at"),
                "incidents": len(run["cases"]),
                "release": release_of(run),
            }
            for run in run_list
        ]
        for name, run_list in runs.items()
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo_url": REPO_URL,
        "runs": runs_info,
        "categories": {c.id: {"title": c.title, "definition": c.definition} for c in CATEGORIES.values()},
        "actions": {
            a.id: {"description": a.description, "approver_role": a.approver_role}
            for a in REMEDIATION_CATALOG.values()
        },
        "incidents": incidents,
    }


def build(out_dir: Path, root: Path | None = None, results_dir: Path | None = None) -> Path:
    data = payload(root, results_dir)
    template = resources.files("drc").joinpath("templates/site.html").read_text(encoding="utf-8")
    # Embedded as a JSON data block. Every "<" is escaped, so no value (tool output from an incident can
    # contain anything) can close the <script> element or open a comment inside it.
    serialized = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(template.replace(PLACEHOLDER, serialized), encoding="utf-8")
    return out
