# Evaluation

The goal is not "the agent works". It is three measured properties:

1. it **diagnoses known incidents correctly**, on the platform it was designed around and on one it was not;
2. it **abstains when the evidence does not support a root cause**, instead of inventing one;
3. it **never proposes an unauthorized change**, including when the data tells it to.

## Method

`drc eval` runs an investigator over the 30 incidents in the [benchmark](benchmark.md), applies the same
grounding check and policy to every result, and scores against `benchmark/labels.yml`.

| Metric | Definition |
| --- | --- |
| Diagnosis accuracy (known) | Share of known incidents where the investigator asserted the labeled category (overall and per platform) |
| Correct abstention (novel) | Share of novel incidents where it abstained or named one of the label's acceptable infrastructure categories |
| False abstention (known) | Share of known incidents where it abstained |
| **Confident errors** | Number of incidents, in any split, where it asserted a wrong category. This is the number to drive to zero |
| Localization (known) | Correct category *and* correct source *and* (when labeled) at least one correct column or field |
| Consumer-impact accuracy | Whether it correctly says what consumers can see now (previous version, published with warning or quarantine, inconsistent data) |
| Remediation relevance | Share of diagnoses with at least one allowed proposal from the label's action list |
| Citations verified | Share of citations whose quote was found verbatim in the cited tool output |
| Withheld | Diagnoses converted to abstentions because no citation verified |
| Injection resistance | Adversarial incidents diagnosed correctly with no forbidden action proposed |
| Safety counters | Policy-rejected proposals, forbidden actions proposed, calls to tools that do not exist |
| Cost and latency | USD from token usage at list price; p50 and p95 wall-clock seconds per incident |

The benchmark is small (24 known, 3 novel, 3 adversarial), so results are reported as counts in the
per-incident tables, and one incident moves a split's rate by several points. Treat differences of one or
two incidents as noise unless they repeat across runs.

## Results

### Deterministic playbook (baseline), measured

Full report: [`eval/results/baseline.md`](../eval/results/baseline.md). Deterministic, so CI enforces these
numbers exactly ([`eval/gates/baseline.yml`](../eval/gates/baseline.yml)).

| Metric | Value |
| --- | --- |
| Diagnosis accuracy, known: hcip (15) | **100%** |
| Diagnosis accuracy, known: clinical ETL (9, held out from its rules) | **22%** (2 of 9: the two generic infrastructure signatures) |
| Correct abstention, novel (3) | 100% |
| Confident errors | **0** |
| Localization, known | 71% (every diagnosed incident localized correctly) |
| Consumer-impact accuracy | 100% |
| Citations verified | 100% (74 of 74) |
| Injection resistance (3) | 67% (it abstains on the clinical injection case: no rule) |
| Policy rejections / forbidden actions / refused tools | 0 / 0 / 0 |
| Tool calls per incident | 3.7 |

Reading: a purpose-built playbook is excellent where it was built and silent elsewhere. It never guesses,
which is the behavior to keep, but 7 of 9 failures on a newly onboarded pipeline go to a human with no
diagnosis at all. That gap is what the AI agent has to close **without giving up the zero
confident-error and zero unsafe-action properties**.

### Claude agent (`claude-opus-5-5`, effort `high`)

**Not yet run.** The agent loop, request shape, budget handling, refusal handling, grounding and cost
accounting are covered by offline tests against a scripted client (`tests/test_claude_agent.py`), but no
live evaluation results are published here until they have been measured. To produce them:

```bash
export ANTHROPIC_API_KEY=...        # PowerShell: $env:ANTHROPIC_API_KEY="..."
drc eval --agent claude --workers 4
```

This writes `eval/results/claude.json` and `eval/results/claude.md`, with one trace per incident under
`runs/traces/eval-claude/`. Expected cost at list price is a few dollars for all 30 incidents; the report
records the exact figure. The `Evaluate Claude agent` GitHub Actions workflow runs the same thing on demand
with a repository secret.

Questions the live run answers:

- Does it match the playbook on hcip (15 of 15) while closing the clinical transfer gap?
- Does it keep confident errors at zero on the novel split, where a plausible data story is available
  but unsupported (a killed process, a stalled run, a row deleted out of band)?
- Does planted text change its category or its proposals on the adversarial split?
- How many citations fail verification, and do any diagnoses get withheld?
- What does a diagnosis cost, and how does `effort` trade cost against accuracy (`--effort medium`)?

## Known limitations of the evaluation

- **Author bias.** The same person wrote the scenarios, the labels, and the baseline rules. The held-out
  clinical platform and the novel split are the main counterweights; scenarios written by someone else
  would be better.
- **Category granularity.** Some incidents admit two defensible readings (a truncated delivery that also
  adds a column). Labels pick the cause that blocked the run; `acceptable` lists exist for novel incidents
  only.
- **Verbatim grounding checks existence, not relevance.** A real quote can support the wrong claim. Root
  cause and localization are scored separately for that reason.
- **Model variance.** A single run of a stochastic agent is one sample. Repeat runs before drawing
  conclusions from small differences.
