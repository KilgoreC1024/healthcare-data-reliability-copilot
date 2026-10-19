"""Command line: `drc incidents | investigate | eval | approve | audit-log | collect | lab`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from drc.lab import store
from drc.models import Investigation

RUNS = Path("runs")


def _investigator(args: argparse.Namespace):
    from drc.agents import get_investigator

    if args.agent == "claude":
        return get_investigator(
            "claude",
            model=args.model,
            effort=args.effort,
            budget=args.budget,
            fallbacks=not args.no_fallbacks,
        )
    return get_investigator("baseline")


def _load(target: str):
    """A benchmark incident id, or a bundle path whose catalog sits beside it (<root>/incidents, <root>/catalog)."""
    bundle = store.load_bundle(target)
    platform = bundle.incident.platform
    root = Path(target).parent.parent
    local = Path(target).is_file() and (root / "catalog" / f"{platform}.json").is_file()
    return bundle, store.load_catalog(platform, root if local else None)


def cmd_incidents(args: argparse.Namespace) -> int:
    for incident_id in store.list_incidents():
        incident = store.load_bundle(incident_id).incident
        print(f"{incident_id}  {incident.platform:13} {incident.signal:24} {incident.headline[:80]}")
    return 0


def cmd_investigate(args: argparse.Namespace) -> int:
    from drc.report import render
    from drc.tracing import Tracer

    bundle, catalog = _load(args.incident)
    tracer = Tracer(RUNS / "traces" / f"{bundle.incident.incident_id}-{args.agent}.jsonl")
    investigation = _investigator(args).investigate(bundle, catalog, tracer)
    tracer.flush()
    saved = RUNS / "investigations" / f"{bundle.incident.incident_id}-{args.agent}.json"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(investigation.model_dump_json(indent=1), encoding="utf-8")
    if args.json:
        print(investigation.model_dump_json(indent=1))
    else:
        print(render(investigation, show_tools=not args.quiet))
        print(f"\nsaved {saved.as_posix()} | trace {tracer.path.as_posix()}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from drc import evaluation

    def progress(case: dict) -> None:
        if "predicted" not in case:
            print(f"  {case['incident_id']}  {case['outcome']}", flush=True)
            return
        print(
            f"  {case['incident_id']}  {case['outcome']:9} {str(case['predicted'] or '(abstained)'):40} "
            f"${case['cost_usd']:.3f}  {case['latency_s']:.1f}s",
            flush=True,
        )

    investigator = _investigator(args)
    result = evaluation.run(
        investigator,
        incident_ids=args.incident or None,
        split=args.split,
        workers=args.workers,
        trace_dir=RUNS / "traces" / f"eval-{args.agent}",
        on_result=progress,
        max_cost_usd=args.max_cost,
    )
    out = Path(args.out or f"eval/results/{args.agent}.json")
    json_path, md_path = evaluation.write_results(result, out)
    print(
        f"\n{json.dumps(result['metrics'], indent=1)}\n\nwrote {json_path.as_posix()} and {md_path.as_posix()}"
    )
    if args.gate:
        failures = evaluation.check_gates(result["metrics"], Path(args.gate))
        for failure in failures:
            print(f"GATE FAILED: {failure}", file=sys.stderr)
        return 1 if failures else 0
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    from drc import approval

    investigation = Investigation.model_validate_json(Path(args.investigation).read_text(encoding="utf-8"))
    try:
        record = approval.decide(
            investigation,
            args.proposal,
            args.approver,
            args.role,
            args.decision,
            args.note or "",
            RUNS / "approvals.jsonl",
            RUNS / "change_requests",
        )
    except approval.ApprovalError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=1, ensure_ascii=False))
    return 0


def cmd_audit_log(args: argparse.Namespace) -> int:
    from drc.approval import verify_log

    ok, count, message = verify_log(RUNS / "approvals.jsonl")
    print(f"{'OK' if ok else 'TAMPERED'}: {count} decision(s); {message}")
    return 0 if ok else 1


def cmd_collect(args: argparse.Namespace) -> int:
    from drc.collectors import hcip

    bundle, catalog = hcip.collect(Path(args.data_dir), Path(args.hcip_home), run_id=args.run_id)
    out = Path(args.out)
    store.write_catalog(catalog, out)
    path = store.write_bundle(bundle, out)
    print(
        f"{bundle.incident.incident_id}: {bundle.incident.signal} - {bundle.incident.headline[:120]}\nwrote {path.as_posix()}"
    )
    return 0


def cmd_lab(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else None
    if args.platform == "hcip":
        from drc.lab import hcip_lab

        hcip_lab.build(Path(args.home), args.only or None, out)
    else:
        from drc.lab import clinical_lab

        clinical_lab.build(Path(args.home), args.only or None, out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drc", description="Healthcare Data Reliability Copilot")
    sub = parser.add_subparsers(dest="command", required=True)

    def agent_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--agent", choices=["baseline", "claude"], default="baseline")
        p.add_argument("--model", default="claude-opus-5-5")
        p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], default="high")
        p.add_argument("--budget", type=int, default=24, help="maximum tool calls per investigation")
        p.add_argument("--no-fallbacks", action="store_true", help="disable server-side refusal fallback")

    p = sub.add_parser("incidents", help="list benchmark incidents")
    p.set_defaults(func=cmd_incidents)

    p = sub.add_parser("investigate", help="investigate one incident (benchmark id or bundle path)")
    p.add_argument("incident")
    agent_options(p)
    p.add_argument("--json", action="store_true", help="print the full investigation as JSON")
    p.add_argument("--quiet", action="store_true", help="omit the tool-call listing")
    p.set_defaults(func=cmd_investigate)

    p = sub.add_parser("eval", help="run the benchmark and score an investigator")
    agent_options(p)
    p.add_argument("--split", choices=["known", "novel", "adversarial"])
    p.add_argument("--incident", action="append", help="limit to these incident ids (repeatable)")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--out", help="results path (default eval/results/<agent>.json)")
    p.add_argument("--gate", help="YAML file of metric thresholds; exit 1 if any is violated")
    p.add_argument(
        "--max-cost",
        type=float,
        help="spend cap in USD: no new investigation starts once spend plus a running reserve would exceed it",
    )
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("approve", help="record a human decision on a remediation proposal")
    p.add_argument("investigation", help="a saved investigation (runs/investigations/*.json)")
    p.add_argument("--proposal", type=int, required=True, help="proposal number, starting at 1")
    p.add_argument("--approver", required=True)
    p.add_argument(
        "--role", required=True, help="data_owner, data_steward, platform_engineer, incident_commander"
    )
    p.add_argument("--decision", choices=["approve", "reject"], required=True)
    p.add_argument("--note")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("audit-log", help="verify the hash chain of recorded decisions")
    p.set_defaults(func=cmd_audit_log)

    p = sub.add_parser("collect", help="build an incident bundle from a live hcip data directory")
    p.add_argument("--data-dir", required=True, help="hcip data root (contains lakehouse/ and warehouse/)")
    p.add_argument("--hcip-home", required=True, help="hcip checkout (contracts/, docs/)")
    p.add_argument("--run-id", help="default: the most recent run")
    p.add_argument("--out", default="runs/collected")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("lab", help="re-create benchmark incidents by running a real pipeline")
    p.add_argument("platform", choices=["hcip", "clinical"])
    p.add_argument("--home", required=True, help="checkout of the pipeline repository")
    p.add_argument("--only", action="append", help="scenario key or incident id (repeatable)")
    p.add_argument("--out", help="benchmark directory (default ./benchmark)")
    p.set_defaults(func=cmd_lab)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
