# Runbook: operating the copilot

## Investigate an incident

Benchmark incident, offline and free:

```bash
drc incidents                              # list the 41 benchmark incidents
drc investigate INC-H11                    # deterministic playbook
```

With the Claude agent (needs `ANTHROPIC_API_KEY`):

```bash
drc investigate INC-C02 --agent claude
drc investigate INC-C02 --agent claude --effort medium     # cheaper; compare results before switching
```

A live hcip run (any data directory hcip has written to):

```bash
drc collect --data-dir ../healthcare-cost-utilization-platform --hcip-home ../healthcare-cost-utilization-platform
drc investigate runs/collected/incidents/hcip-<run_id>.json --agent claude
```

`drc collect` opens hcip's DuckDB files read-only. It picks the most recent run unless you pass `--run-id`,
and exits with an error if that run completed cleanly (nothing to investigate).

Every investigation is saved to `runs/investigations/` and traced to `runs/traces/`.

## Read the report

- **DIAGNOSIS** or **ABSTAINED**. An abstention is a valid result: the copilot found that the evidence does
  not support a specific root cause. Read `reason` and the open questions; they say what to look at next.
- **Evidence** lines are marked `verified` (the quote exists in the cited tool output) or `UNVERIFIED`.
  Treat unverified lines as hypotheses. If no line verifies, the diagnosis is withheld automatically.
- **Consumer impact** says what consumers see now. `previous_version_served` means nothing from the
  failing run reached them; `inconsistent_data_served` means it did, and it is the only case where a
  rollback can be proposed.
- **Guardrail events** list refused tool calls, unverified citations, policy rejections, fallback models,
  and budget exhaustion. Any refused tool call on a real incident deserves a look at the trace.

## Approve or reject a proposal

```bash
drc approve runs/investigations/INC-H12-claude.json --proposal 1 \
    --approver "Your Name" --role data_owner --decision approve --note "Confirmed with CMS"
drc audit-log
```

- The role must match the action's approver role in the catalog (`data_owner`, `data_steward`,
  `platform_engineer`, `incident_commander`). A mismatch is refused.
- A proposal the policy rejected cannot be decided.
- Approval writes `runs/change_requests/<incident>-<n>-<action>.md`. Carry it out through the normal
  process: a pull request for a contract change, a message to the provider, `hcip rollback <run_id>` for a
  rollback. The copilot does not execute anything.
- `drc audit-log` recomputes the decision log's hash chain and exits non-zero if a record was altered.

## Evaluate

```bash
drc eval --agent baseline --gate eval/gates/baseline.yml     # offline, about a second; CI runs this
drc eval --agent claude --workers 2 --max-cost 4.50          # live, about $2.75; writes eval/results/claude.{json,md}
drc eval --agent claude --split novel                        # one split
drc eval --agent claude --incident INC-H16 --incident INC-C09
```

`--max-cost` is a hard spend cap in USD. A new investigation starts only if the amount spent, plus a reserve
for every investigation still running (the most expensive one so far, at least $0.30), stays within the cap.
Incidents it skips are listed in the report and left out of the metrics. With prepaid API credit, set the
cap below your balance.

Commit results files only from runs you intend to publish, and record the model and effort (the results
file does this in `config`).

## Regenerate the benchmark

See [benchmark.md](benchmark.md#regenerating). Re-run `pytest` afterwards; the integrity tests fail if any
label leaks into a bundle or a local path survives redaction.

## Troubleshooting

| Symptom | Cause and action |
| --- | --- |
| `AuthenticationError` | `ANTHROPIC_API_KEY` missing or wrong in this shell |
| `RateLimitError` after retries | Lower `--workers`; the SDK already retries 429s with backoff |
| Many `unverified citation` events | The model paraphrased quotes. Check the trace; if it persists after a model or prompt change, treat it as a regression |
| `tool budget exhausted` on most incidents | The investigation path got longer (new tools, bigger outputs). Inspect traces before raising `--budget` |
| `served by fallback model` | A safety classifier declined and the server retried on another model. Results from that incident came from the fallback model |
| `the hcip collector needs DuckDB` | `pip install -e ".[collect]"` |
| `run ... finished 'published' with no new warnings` | The selected run is healthy; pass `--run-id` for the run you mean |
