"""Collector for the Healthcare Cost & Utilization Intelligence Platform (hcip).

Reads, never writes (DuckDB files are opened read-only):

    warehouse/ops.duckdb                          run ledger: runs, steps, checks, source releases
    lakehouse/landing/<source>/release_id=<id>/   landed file, manifest, contract report
    warehouse/runs/<run_id>/                      dbt log, compiled tests, manifest, candidate database
    lakehouse/gold/_CURRENT.json                  which run consumers currently see
    <hcip checkout>/contracts, docs               data contracts and runbooks

https://github.com/KilgoreC1024/healthcare-cost-utilization-platform
"""

from __future__ import annotations

import json
import re
from contextlib import closing
from pathlib import Path
from typing import Any

import yaml

from drc.collectors.common import (
    jsonable,
    load_knowledge,
    maybe_json,
    platform_registry,
    sig,
    strip_ansi,
    tail,
)
from drc.models import Catalog, Evidence, Incident, IncidentBundle

PLATFORM = "hcip"
NUMERIC = ("integer", "decimal")
MAX_ROWS = 20


class NoIncident(ValueError):
    """The run completed cleanly; there is nothing to investigate."""


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError("the hcip collector needs DuckDB: pip install 'drc[collect]'") from exc
    return duckdb


def _ident(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


# ---- run ledger ------------------------------------------------------------------------------------
class Ledger:
    def __init__(self, path: Path):
        if not path.is_file():
            raise FileNotFoundError(f"no hcip run ledger at {path}")
        self.path = path

    def query(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        with closing(_duckdb().connect(str(self.path), read_only=True)) as con:
            cursor = con.execute(sql, params or [])
            names = [d[0] for d in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def run(self, run_id: str | None) -> dict[str, Any]:
        rows = (
            self.query("SELECT * FROM pipeline_runs WHERE run_id = ?", [run_id])
            if run_id
            else self.query("SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1")
        )
        if not rows:
            raise KeyError(f"run not found in ledger: {run_id}")
        return rows[0]

    def steps(self, run_id: str) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM step_runs WHERE run_id = ? ORDER BY started_at", [run_id])

    def checks(self, run_id: str) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM check_results WHERE run_id = ? ORDER BY recorded_at", [run_id])

    def releases(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM source_releases ORDER BY landed_at")

    def previous_published_run(self, run: dict[str, Any]) -> str | None:
        rows = self.query(
            "SELECT run_id FROM pipeline_runs WHERE status = 'published' AND started_at < ? "
            "ORDER BY started_at DESC LIMIT 1",
            [run["started_at"]],
        )
        return rows[0]["run_id"] if rows else None


# ---- profiling ---------------------------------------------------------------------------------------
def read_csv_sql(path: Path) -> str:
    """The same pinned CSV dialect hcip uses, so the profile sees exactly what the contract saw."""
    return (
        f"read_csv({_lit(path.resolve().as_posix())}, header = true, all_varchar = true, strict_mode = true, "
        "delim = ',', quote = '\"', escape = '\"', skip = 0, null_padding = false, hive_partitioning = false)"
    )


def profile_file(path: Path, columns: dict[str, dict[str, Any]], sentinels: list[str]) -> dict[str, Any]:
    """Column profiles of a landed CSV: counts, sentinel use, parse failures, distribution, examples."""
    duckdb = _duckdb()
    con = duckdb.connect()
    try:
        con.execute(f"CREATE TABLE src AS SELECT * FROM {read_csv_sql(path)}")
    except duckdb.Error as exc:
        con.close()
        return {"_error": str(exc).splitlines()[0]}
    try:
        present = [r[0] for r in con.execute("DESCRIBE src").fetchall()]
        rows = con.execute("SELECT count(*) FROM src").fetchone()[0]
        out: dict[str, Any] = {"_rows": rows}
        not_sentinel = f"NOT IN ({', '.join(_lit(s) for s in sentinels)})" if sentinels else "IS NOT NULL"
        for column, spec in columns.items():
            if column not in present:
                out[column] = {"present": False}
                continue
            c = _ident(column)
            usable = f"{c} IS NOT NULL AND {c} {not_sentinel}"
            nulls, distinct = con.execute(
                f"SELECT count(*) FILTER (WHERE {c} IS NULL), count(DISTINCT {c}) FROM src"
            ).fetchone()
            prof: dict[str, Any] = {"present": True, "nulls": nulls, "distinct": distinct}
            if sentinels:
                counts = con.execute(
                    f"SELECT {c}, count(*) FROM src WHERE {c} IN ({', '.join(_lit(s) for s in sentinels)}) GROUP BY 1"
                ).fetchall()
                if counts:
                    prof["sentinels"] = {k: n for k, n in counts}
            kind = spec.get("type", "string")
            if kind in NUMERIC:
                bad = con.execute(
                    f"SELECT count(*) FROM src WHERE {usable} AND TRY_CAST({c} AS DOUBLE) IS NULL"
                ).fetchone()[0]
                prof["non_numeric"] = bad
                if bad:
                    prof["non_numeric_examples"] = [
                        r[0]
                        for r in con.execute(
                            f"SELECT DISTINCT {c} FROM src WHERE {usable} AND TRY_CAST({c} AS DOUBLE) IS NULL "
                            "ORDER BY 1 LIMIT 3"
                        ).fetchall()
                    ]
                stats = con.execute(
                    f"SELECT min(v), quantile_cont(v, 0.5), avg(v), max(v) FROM "
                    f"(SELECT TRY_CAST({c} AS DOUBLE) AS v FROM src WHERE {usable}) WHERE v IS NOT NULL"
                ).fetchone()
                prof.update(zip(("min", "median", "mean", "max"), (sig(v) for v in stats), strict=True))
            if "pattern" in spec:
                predicate = f"{usable} AND NOT regexp_full_match({c}, {_lit(spec['pattern'])})"
                violations = con.execute(f"SELECT count(*) FROM src WHERE {predicate}").fetchone()[0]
                prof["pattern"] = spec["pattern"]
                prof["pattern_violations"] = violations
                if violations:
                    prof["pattern_violation_examples"] = [
                        r[0]
                        for r in con.execute(
                            f"SELECT DISTINCT {c} FROM src WHERE {predicate} ORDER BY 1 LIMIT 3"
                        ).fetchall()
                    ]
            if kind not in NUMERIC:
                if distinct <= 10:
                    prof["values"] = {
                        str(k): n
                        for k, n in con.execute(
                            f"SELECT {c}, count(*) FROM src GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10"
                        ).fetchall()
                    }
                else:
                    prof["examples"] = [
                        r[0]
                        for r in con.execute(
                            f"SELECT DISTINCT {c} FROM src WHERE {c} IS NOT NULL ORDER BY 1 LIMIT 3"
                        ).fetchall()
                    ]
            out[column] = prof
        return out
    finally:
        con.close()


# ---- collection --------------------------------------------------------------------------------------
def _landing(data_root: Path, source: str, release_id: str) -> Path:
    return data_root / "lakehouse" / "landing" / source / f"release_id={release_id}"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def load_contracts(project_root: Path) -> dict[str, Any]:
    contracts = {}
    for path in sorted((project_root / "contracts").glob("*.yml")):
        contract = yaml.safe_load(path.read_text(encoding="utf-8"))
        contracts[contract["source"]] = contract
    return contracts


def build_lineage(manifest: dict[str, Any]) -> dict[str, Any]:
    """Compact dbt lineage: sources, seeds and models; which models each test reads; parent -> child edges."""
    names: dict[str, str] = {}
    nodes: dict[str, Any] = {}
    for uid, src in manifest.get("sources", {}).items():
        name = f"{src['source_name']}.{src['name']}"
        names[uid] = name
        nodes[name] = {
            "type": "source",
            "layer": "bronze",
            "description": (src.get("description") or "")[:240],
        }
    for uid, node in manifest.get("nodes", {}).items():
        if node["resource_type"] in ("model", "seed"):
            names[uid] = node["name"]
            nodes[node["name"]] = {
                "type": node["resource_type"],
                "layer": node.get("schema"),
                "description": (node.get("description") or "")[:240],
            }
    edges, tests = [], {}
    for node in manifest.get("nodes", {}).values():
        parents = [names[p] for p in node.get("depends_on", {}).get("nodes", []) if p in names]
        if node["resource_type"] in ("model", "seed"):
            edges.extend([p, node["name"]] for p in parents)
        elif node["resource_type"] == "test":
            tests[node["name"]] = sorted(set(parents))
    return {"nodes": nodes, "edges": sorted(edges), "tests": dict(sorted(tests.items()))}


def _manifest(data_root: Path, run_id: str) -> dict[str, Any] | None:
    own = data_root / "warehouse" / "runs" / run_id / "dbt" / "target" / "manifest.json"
    candidates = [own] + sorted(
        (data_root / "warehouse" / "runs").glob("*/dbt/target/manifest.json"), reverse=True
    )
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def build_catalog(data_root: Path, project_root: Path, run_id: str) -> Catalog:
    registry = platform_registry()[PLATFORM]
    manifest = _manifest(data_root, run_id)
    return Catalog(
        platform=PLATFORM,
        sources=registry["sources"],
        contracts=load_contracts(project_root),
        lineage=build_lineage(manifest) if manifest else {},
        consumers=registry["consumers"],
        knowledge=load_knowledge(project_root, registry["knowledge"]),
    )


def _dbt_test_detail(data_root: Path, run_id: str, check: dict[str, Any]) -> dict[str, Any]:
    run_dir = data_root / "warehouse" / "runs" / run_id
    detail = {k: check[k] for k in ("check_name", "status", "observed", "expected", "message")}
    compiled = next(
        iter(sorted((run_dir / "dbt" / "target" / "compiled").rglob(f"{check['check_name']}.sql"))), None
    )
    if compiled is None:
        return detail
    sql = compiled.read_text(encoding="utf-8")
    detail["sql"] = sql[:4000]
    candidate = run_dir / "hcip.duckdb"
    if candidate.is_file():
        duckdb = _duckdb()
        try:
            with closing(duckdb.connect(str(candidate), read_only=True)) as con:
                cursor = con.execute(f"SELECT * FROM ({sql.rstrip().rstrip(';')}) LIMIT {MAX_ROWS}")
                names = [d[0] for d in cursor.description]
                detail["failing_rows"] = [
                    jsonable(dict(zip(names, r, strict=True))) for r in cursor.fetchall()
                ]
        except duckdb.Error as exc:
            detail["failing_rows_error"] = str(exc).splitlines()[0]
    return detail


def _release_view(r: dict[str, Any]) -> dict[str, Any]:
    stats = maybe_json(r.get("stats")) or {}
    return jsonable(
        {
            "release_id": r["release_id"],
            "row_count": r["row_count"],
            "contract_status": r["contract_status"],
            "suppression_rate": stats.get("suppression_rate"),
            "bytes": r["bytes"],
            "landed_at": r["landed_at"],
            "accepted_at": r["accepted_at"],
            "published_at": r["published_at"],
            "is_current": r["is_current"],
        }
    )


def collect(
    data_root: str | Path,
    project_root: str | Path,
    run_id: str | None = None,
    incident_id: str | None = None,
) -> tuple[IncidentBundle, Catalog]:
    data_root, project_root = Path(data_root), Path(project_root)
    ledger = Ledger(data_root / "warehouse" / "ops.duckdb")
    run = ledger.run(run_id)
    run_id = run["run_id"]
    steps = [jsonable({**s, "detail": maybe_json(s["detail"])}) for s in ledger.steps(run_id)]
    checks = [
        jsonable({**c, "observed": maybe_json(c["observed"]), "expected": maybe_json(c["expected"])})
        for c in ledger.checks(run_id)
    ]
    releases = ledger.releases()
    catalog = build_catalog(data_root, project_root, run_id)

    # ---- what kind of incident is this? ----------------------------------------------------------------
    status, message = run["status"], run["message"] or ""
    failed_stage = None
    # Warnings that also fired on the last published run are background noise, not this incident.
    previous_run = ledger.previous_published_run(run)
    persisting = sorted(
        {c["check_name"] for c in ledger.checks(previous_run) if c["status"] == "warn"}
        if previous_run
        else set()
    )
    if status == "blocked":
        signal = "run_blocked"
        match = re.match(r"\[(\w+)\]", message)
        failed_stage = match.group(1) if match else None
        headline = message
    elif status == "failed":
        signal = "run_failed"
        failed = [s for s in steps if s["status"] == "failed"]
        failed_stage = failed[0]["step"] if failed else None
        headline = message
    elif run["finished_at"] is None:
        signal = "run_stalled"
        last = steps[-1] if steps else None
        failed_stage = last["step"] if last else None
        headline = (
            f"Run {run_id} started at {jsonable(run['started_at'])} has not finished; last recorded step: "
            + (f"{last['step']} ({last['source'] or 'all sources'}) {last['status']}" if last else "none")
        )
    else:
        # Alert on warnings that are new since the last published run, not on persistent ones.
        new_warnings = sorted({c["check_name"] for c in checks if c["status"] == "warn"} - set(persisting))
        if status != "published" or not new_warnings:
            raise NoIncident(f"run {run_id} finished '{status}' with no new warnings")
        signal = "published_with_warnings"
        headline = f"Run published with new warnings: {', '.join(new_warnings)}"

    incident = Incident(
        incident_id=incident_id or f"{PLATFORM}-{run_id}",
        platform=PLATFORM,
        pipeline=platform_registry()[PLATFORM]["pipeline"],
        run_id=run_id,
        detected_at=jsonable(run["finished_at"] or run["started_at"]),
        signal=signal,
        failed_stage=failed_stage,
        headline=headline[:1000],
    )

    # ---- releases in play per source ---------------------------------------------------------------------
    landed = {s["source"]: (s.get("detail") or {}).get("release_id") for s in steps if s["step"] == "land"}
    by_source: dict[str, list[dict[str, Any]]] = {}
    for r in releases:
        by_source.setdefault(r["source"], []).append(r)
    evidence = Evidence(
        run={
            **jsonable(
                {k: run[k] for k in ("run_id", "profile", "trigger", "started_at", "finished_at", "status")}
            ),
            "message": message,
            "previous_published_run": previous_run,
            "warnings_on_previous_published_run": persisting,
            "steps": steps,
        },
        checks=checks,
        releases={src: [_release_view(r) for r in rs] for src, rs in by_source.items()},
    )

    for source in catalog.sources:
        contract = catalog.contracts.get(source, {})
        current_id = landed.get(source)
        history = by_source.get(source, [])
        current = next((r for r in history if r["release_id"] == current_id), None)
        previous = next(
            (
                r
                for r in reversed(history)
                if r["release_id"] != current_id
                and r["contract_status"] in ("pass", "warn")
                and r["accepted_at"] is not None
                and r["accepted_at"] < run["started_at"]
            ),
            None,
        )
        if current is None and previous is None:
            continue
        cur_header = maybe_json(current["header"]) if current else None
        prev_header = maybe_json(previous["header"]) if previous else None
        if current is None:
            state = "not landed in this run (the run stopped before reaching this source)"
            if not current_id and any(s["step"] == "land" and s["source"] == source for s in steps):
                state = "landing failed in this run"
        elif previous is None:
            state = "unchanged (this run re-validated the already accepted release)"
        else:
            state = "new release landed in this run"
        evidence.schemas[source] = {
            "release_state": state,
            "current_release": current["release_id"] if current else None,
            "previous_release": previous["release_id"] if previous else (current or {}).get("release_id"),
            "current_header": cur_header,
            "previous_header": prev_header if previous else cur_header,
        }
        unchanged = current is None or previous is None
        report = (
            _read_json(_landing(data_root, source, current["release_id"]) / "_contract_report.json")
            if current
            else None
        )
        if report:
            for check in report["checks"]:
                if check["status"] != "pass":
                    evidence.check_details[f"{source}:{check['name']}"] = jsonable(check)
        if unchanged or current is None:
            continue
        columns = dict(contract.get("columns", {}))
        for extra in sorted(set(cur_header or []) ^ set(prev_header or [])):
            columns.setdefault(extra, {"type": "string"})
        sentinels = list((contract.get("sentinels") or {}).keys())
        profiles: dict[str, Any] = {"current_release": current["release_id"]}
        for label, release in (("current", current), ("previous", previous)):
            if release is None:
                continue
            path = _landing(data_root, source, release["release_id"]) / "data.csv"
            if path.is_file():
                profiles[label] = profile_file(path, columns, sentinels)
        profiles["previous_release"] = previous["release_id"] if previous else None
        evidence.profiles[source] = profiles

    for check in checks:
        if check["layer"] == "dbt" and check["status"] in ("fail", "warn", "error"):
            evidence.check_details[check["check_name"]] = _dbt_test_detail(data_root, run_id, check)

    # ---- what consumers see right now ---------------------------------------------------------------------
    pointer = _read_json(data_root / "lakehouse" / "gold" / "_CURRENT.json") or {}
    evidence.publish_state = {
        "served_run_id": pointer.get("run_id"),
        "served_releases": pointer.get("releases"),
        "published_at": pointer.get("published_at"),
        "this_run_is_served": pointer.get("run_id") == run_id,
        "write_audit_publish": "Consumers only see a run after its dbt audit passes; a blocked or failed run "
        "leaves the previously published gold layer in place.",
    }

    # ---- logs ---------------------------------------------------------------------------------------------
    dbt_log = data_root / "warehouse" / "runs" / run_id / "dbt" / "dbt_stdout.log"
    if dbt_log.is_file():
        evidence.logs["dbt"] = tail(strip_ansi(dbt_log.read_text(encoding="utf-8", errors="replace")), 40)
    for step in steps:
        error = (step.get("detail") or {}).get("error")
        if error:
            evidence.logs[f"{step['step']}:{step['source'] or 'all'}"] = error
    return IncidentBundle(incident=incident, evidence=evidence), catalog
