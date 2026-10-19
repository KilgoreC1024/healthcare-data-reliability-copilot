"""Collector for the synthetic clinical ETL (Airflow TaskFlow DAG `synthetic_clinical_etl`).

Input is an Airflow-shaped DAG run record (dag run + task instances with logs), the FHIR-shaped source
bundle the run read, the bundle the previous successful run read, and the SQLite target. The target is
opened read-only (`mode=ro`).

https://github.com/KilgoreC1024/airflow-synthetic-clinical-etl
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from drc.collectors.common import load_knowledge, platform_registry
from drc.models import Catalog, Evidence, Incident, IncidentBundle

PLATFORM = "clinical_etl"
SOURCE = "synthetic_fhir_bundle"
TASKS = ["extract", "transform", "quality_gate", "load", "audit"]
TABLES = ["patients", "encounters", "conditions"]
GATE_CHECKS = {
    "extract": "extract.bundle_structure",
    "transform": "transform.resource_parsing",
    "quality_gate": "quality_gate.validate_tables",
    "load": "load.transactional_refresh",
    "audit": "audit.post_load",
}


def build_catalog(clinical_home: Path) -> Catalog:
    registry = platform_registry()[PLATFORM]
    nodes = {SOURCE: {"type": "source", "layer": "landing", "description": "FHIR R4-shaped JSON Bundle"}}
    edges = []
    previous = SOURCE
    for task in TASKS:
        nodes[f"task.{task}"] = {
            "type": "task",
            "layer": "airflow",
            "description": registry["contract"]["gates"][task],
        }
        edges.append([previous, f"task.{task}"])
        previous = f"task.{task}"
    for table in TABLES:
        nodes[table] = {
            "type": "table",
            "layer": "sqlite",
            "description": ", ".join(registry["contract"]["tables"][table]),
        }
        edges.append(["task.load", table])
    return Catalog(
        platform=PLATFORM,
        sources=registry["sources"],
        contracts={SOURCE: registry["contract"]},
        lineage={
            "nodes": nodes,
            "edges": edges,
            "tests": {GATE_CHECKS[t]: [f"task.{t}"] for t in TASKS},
        },
        consumers=registry["consumers"],
        knowledge=load_knowledge(clinical_home, registry["knowledge"]),
    )


# ---- source profiling --------------------------------------------------------------------------------
def _flatten(value: Any, prefix: str, out: dict[str, list[Any]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _flatten(child, f"{prefix}.{key}", out)
    elif isinstance(value, list):
        for child in value:
            _flatten(child, f"{prefix}[]", out)
    else:
        out.setdefault(prefix, []).append(value)


def read_bundle(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Parse the source file and describe it, recording parse errors rather than raising."""
    raw = path.read_bytes() if path.is_file() else None
    info: dict[str, Any] = {"present": raw is not None}
    if raw is None:
        return None, info
    info.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()[:16])
    try:
        bundle = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        info["parse_error"] = f"{type(exc).__name__}: {exc}"
        info["last_80_chars"] = raw.decode("utf-8", errors="replace")[-80:]
        return None, info
    entries = bundle.get("entry") if isinstance(bundle, dict) else None
    info.update(
        resourceType=bundle.get("resourceType") if isinstance(bundle, dict) else None,
        type=bundle.get("type") if isinstance(bundle, dict) else None,
        entries=len(entries) if isinstance(entries, list) else None,
    )
    return bundle, info


def resources(bundle: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not bundle:
        return []
    return [
        e["resource"]
        for e in bundle.get("entry", [])
        if isinstance(e, dict) and isinstance(e.get("resource"), dict)
    ]


def field_paths(bundle: dict[str, Any] | None) -> list[str] | None:
    if bundle is None:
        return None
    paths: dict[str, list[Any]] = {}
    for res in resources(bundle):
        _flatten(res, str(res.get("resourceType", "?")), paths)
    return sorted(paths)


def profile_bundle(bundle: dict[str, Any] | None) -> dict[str, Any]:
    res = resources(bundle)
    by_type: dict[str, int] = {}
    for r in res:
        by_type[str(r.get("resourceType"))] = by_type.get(str(r.get("resourceType")), 0) + 1
    ids = {f"{r.get('resourceType')}/{r.get('id')}" for r in res}
    values: dict[str, list[Any]] = {}
    for r in res:
        _flatten(r, str(r.get("resourceType", "?")), values)
    out: dict[str, Any] = {"_rows": len(res), "_resource_types": by_type}
    for path, vals in sorted(values.items()):
        kind = path.split(".", 1)[0]
        prof: dict[str, Any] = {
            "present": True,
            "count": len(vals),
            "missing": by_type.get(kind, 0) - len(vals) if "[]" not in path else None,
            "distinct": len({json.dumps(v) for v in vals}),
        }
        if prof["distinct"] <= 8:
            counts: dict[str, int] = {}
            for v in vals:
                counts[str(v)] = counts.get(str(v), 0) + 1
            prof["values"] = counts
        else:
            prof["examples"] = sorted({str(v) for v in vals})[:3]
        if path.endswith(".reference"):
            prof["unresolved_references"] = sum(1 for v in vals if isinstance(v, str) and v not in ids)
        if path.endswith((".start", ".end")):
            prof["without_timezone"] = sum(
                1 for v in vals if isinstance(v, str) and not re.search(r"(Z|[+-]\d\d:\d\d)$", v)
            )
        out[path] = prof
    return out


def _records_in_message(message: str, bundle: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The source records an error message names (e.g. 'Encounter/enc-003'), as an engineer would pull them."""
    wanted = set(re.findall(r"\b(Patient|Encounter|Condition|Observation)/([\w.-]+)", message))
    return [r for r in resources(bundle) if (r.get("resourceType"), r.get("id")) in wanted][:10]


def target_state(db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        return {"exists": False}
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as con:
        counts = {}
        for table in TABLES:
            try:
                counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            except sqlite3.Error as exc:
                counts[table] = f"error: {exc}"
    return {"exists": True, "row_counts": counts}


# ---- collection --------------------------------------------------------------------------------------
def collect(
    run: dict[str, Any],
    history: list[dict[str, Any]],
    source_path: Path,
    previous_source_path: Path | None,
    db_path: Path,
    incident_id: str | None = None,
) -> IncidentBundle:
    registry = platform_registry()[PLATFORM]
    tasks = {t["task_id"]: t for t in run["task_instances"]}
    failed = [t for t in TASKS if tasks.get(t, {}).get("state") == "failed"]
    if run["state"] == "success" or not failed:
        raise ValueError(f"DAG run {run['run_id']} has no failed task")
    stage = failed[0]
    error = tasks[stage].get("exception", "")
    incident = Incident(
        incident_id=incident_id or f"{PLATFORM}-{run['run_id']}",
        platform=PLATFORM,
        pipeline=registry["pipeline"],
        run_id=run["run_id"],
        detected_at=run["end_date"],
        signal="run_failed",
        failed_stage=stage,
        headline=(
            f"DAG synthetic_clinical_etl run {run['run_id']} failed in task '{stage}'"
            + (f": {error}" if error else "")
        )[:1000],
    )

    current, current_info = read_bundle(source_path)
    previous, previous_info = read_bundle(previous_source_path) if previous_source_path else (None, {})
    gates = registry["contract"]["gates"]
    checks = []
    for task in TASKS:
        ti = tasks.get(task, {"state": "not_run"})
        status = {"success": "pass", "failed": "fail"}.get(ti["state"], ti["state"])
        checks.append(
            {
                "layer": task,
                "source": SOURCE,
                "check_name": GATE_CHECKS[task],
                "status": status,
                "observed": ti.get("exception") or ti.get("result"),
                "expected": gates[task],
                "message": ti.get("exception", ""),
            }
        )
    evidence = Evidence(
        run={
            "run_id": run["run_id"],
            "dag_id": run["dag_id"],
            "state": run["state"],
            "run_type": run.get("run_type"),
            "start_date": run["start_date"],
            "end_date": run["end_date"],
            "steps": [
                {
                    "step": t["task_id"],
                    "status": t["state"],
                    "try_number": t.get("try_number"),
                    "duration_s": t.get("duration_s"),
                }
                for t in run["task_instances"]
            ],
        },
        checks=checks,
        check_details={
            f"{SOURCE}:{GATE_CHECKS[stage]}": {
                "task_id": stage,
                "exception_type": tasks[stage].get("exception_type"),
                "message": error,
                "records_named_in_error": _records_in_message(error, current),
            }
        },
        schemas={
            SOURCE: {
                "release_state": "new source file read by this run",
                "current_release": f"bundle-{current_info.get('sha256', 'missing')[:8]}",
                "previous_release": f"bundle-{previous_info.get('sha256', 'none')[:8]}"
                if previous_info
                else None,
                "current_header": field_paths(current),
                "previous_header": field_paths(previous),
                "current_file": current_info,
                "previous_file": previous_info or None,
            }
        },
        profiles={
            SOURCE: {
                "current_release": f"bundle-{current_info.get('sha256', 'missing')[:8]}",
                "current": profile_bundle(current)
                if current
                else {"_error": current_info.get("parse_error", "unreadable")},
                "previous": profile_bundle(previous) if previous else None,
                "previous_release": f"bundle-{previous_info.get('sha256', 'none')[:8]}"
                if previous_info
                else None,
            }
        },
        releases={
            SOURCE: [
                {
                    "release_id": f"bundle-{h['source_sha256'][:8]}" if h.get("source_sha256") else None,
                    "run_id": h["run_id"],
                    "state": h["state"],
                    "loaded_row_counts": h.get("loaded_row_counts"),
                    "end_date": h["end_date"],
                }
                for h in [*history, run]
            ]
        },
        publish_state={
            "target": "runtime/clinical_demo.sqlite",
            **target_state(db_path),
            "last_successful_run_id": next(
                (h["run_id"] for h in reversed(history) if h["state"] == "success"), None
            ),
            "this_run_loaded": tasks.get("load", {}).get("state") == "success",
            "load_semantics": "load is a transactional full refresh (BEGIN IMMEDIATE ... COMMIT); if load or an "
            "earlier task fails, the previous tables remain unchanged",
        },
        logs={
            t["task_id"]: t["log"] for t in run["task_instances"] if t.get("log") and t["state"] == "failed"
        },
    )
    return IncidentBundle(incident=incident, evidence=evidence)
