# Threat model

Scope: the copilot as built in release 1 (collectors, read-only tools, investigators, grounding, policy,
approval, evaluation), run by a data-platform team against its own pipelines. The model provider is
Anthropic's Claude API.

## Assets

| Asset | Why it matters |
| --- | --- |
| Published data (gold tables, clinical target tables) | Consumers make decisions from it; a wrong rollback or deletion harms them |
| Incident evidence (samples, profiles, logs) | In a real deployment it can contain sensitive values, including PHI |
| Remediation decisions and change requests | They authorize changes; their integrity is an audit requirement |
| The API credential | Spend and data access |
| Evaluation results | They justify trusting the copilot; gamed results justify misplaced trust |

## Trust boundaries

1. Upstream data → pipeline → run metadata. Everything that originates upstream is untrusted: file
   contents, column names, values, error messages that echo values, and the alert text itself.
2. Copilot → model provider. Tool outputs leave the platform as prompt content.
3. Investigator → human approver. Recommendations cross from an automated system to an accountable person.

## Threats and controls

| # | Threat | Controls | Verified by | Residual risk |
| --- | --- | --- | --- | --- |
| T1 | **Prompt injection through data**: a column name, value, record field, or log line tells the model to change its conclusion or recommend a destructive action | No write tools exist; data is labeled untrusted in the system prompt and the alert is wrapped; output schema restricts categories and actions to enums; the policy check reads the evidence, not the model's claims; grounding requires verbatim evidence | Adversarial split (`INC-H18`, `INC-H19`, `INC-C10`) scores category correctness and forbidden actions; tool tests refuse unknown tools | Injected text can still color the narrative summary; the approver sees verified evidence and the change request lists only verified quotes |
| T2 | **Excessive agency**: the model takes or triggers actions | Read-only tool allowlist; collectors open databases read-only; the copilot never executes remediation; approval produces a document | `test_unknown_tools_are_refused_and_recorded`, `test_write_tools_do_not_exist_and_attempts_are_recorded` | None inside the copilot; outside it, a person executes approved changes through normal controls |
| T3 | **Fabricated evidence or root cause** | Mechanical citation verification; diagnoses without verified evidence are withheld; abstention is an explicit, rewarded outcome | `test_guardrails.py`, `test_fabricated_evidence_gets_the_diagnosis_withheld`; novel split and confident-error count | A real but irrelevant quote passes verification; correctness is measured separately |
| T4 | **Sensitive data sent to the model provider** | Benchmark uses only public CMS/CDC data and fictional FHIR-shaped records; collectors send profiles and at most a few sample values per check; tool outputs are capped at 9,000 characters | Benchmark integrity tests check for leaked local paths and user names | For real PHI: run under a business associate agreement and a data-retention arrangement that meets policy, or through a cloud platform deployment in your tenant; add a sample-redaction hook to collectors (roadmap) |
| T5 | **Unauthorized or tampered approvals** | Role must match the catalog's approver role; policy-rejected proposals cannot be decided; hash-chained decision log | `test_approval_requires_the_catalog_role_and_chains_every_decision` (including a tampering test) | Roles are asserted by the caller in release 1; replacing the whole log file is not detected until the head hash is anchored externally (roadmap) |
| T6 | **Cost runaway or denial of service** | 24-tool-call budget, turn limit, `max_tokens`, capped tool output; per-incident cost recorded | `test_budget_exhaustion_forces_a_final_answer_without_tools` | Batch evaluation spend is bounded by the number of incidents; set organization spend limits on the API key |
| T7 | **Evaluation gaming or label leakage** | Labels in a separate file; opaque ids and neutral release ids; scenario names rejected by the lab; the fault-injection answer key excluded from the knowledge base | `test_benchmark_integrity.py` | The author wrote both the scenarios and the baseline rules; the clinical platform is held out from the rules to expose that bias |
| T8 | **Model unavailable or declining** | Server-side refusal fallback; remaining refusals become abstentions; API errors are reported as errors, not abstentions; the deterministic baseline is a degraded mode | `test_refusal_becomes_an_abstention`, `test_fallback_model_usage_is_recorded` | A fallback model may perform differently; which model served each turn is recorded |
| T9 | **Over-trust by people** | Reports mark each citation verified or unverified, show confidence and consumer impact, and say "abstained" plainly; change requests include only verified evidence | Report rendering and change-request tests | Organizational: approvers need to read the evidence |
| T10 | **Supply chain** | Three runtime dependencies with major-version pins; CI on Linux and Windows | CI | Standard dependency risk |
