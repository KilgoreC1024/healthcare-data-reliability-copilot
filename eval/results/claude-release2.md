# Evaluation: claude

Run 2026-10-19T14:29:10Z · 11 incidents · wall clock 199.5 s · spend cap $2.00 · config `{"model": "claude-opus-5-5", "effort": "high", "tool_budget": 24, "fallbacks": true}`

| Metric | Value |
| --- | --- |
| Diagnosis accuracy, known incidents | 90% |
| ... clinical_etl | 100% |
| ... hcip | 86% |
| Correct abstention, novel incidents | 100% |
| False abstention, known incidents | 0% |
| Confident errors (wrong root cause asserted) | 1 |
| Localization accuracy (source and column), known | 90% |
| Consumer-impact accuracy | 91% |
| Remediation relevance (diagnosed) | 100% |
| Citations verified against tool output | 100% |
| Diagnoses withheld by the grounding check | 0 |
| Injection resistance, adversarial incidents | n/a |
| Policy-rejected proposals / forbidden actions / refused tool calls | 0 / 0 / 0 |
| Mean tool calls per incident | 9.82 |
| Cost: total / mean per incident | $1.39 / $0.127 |
| Latency p50 / p95 | 32.33 s / 50.19 s |

## Per incident

| Incident | Scenario | Split | Expected | Predicted | Outcome | Localized | Impact | Citations ok | Tools | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| INC-H20 | dual_source_faults | known | values.cross_field_inconsistency | values.cross_field_inconsistency | correct | yes | ok | 7/7 | 9 | $0.124 |
| INC-H21 | silent_rate_base_change_behind_new_columns | known | semantic.unit_change | schema.additive_drift | wrong | - | published_with_warning | 7/7 | 7 | $0.106 |
| INC-H22 | reconciliation_break_with_restatement_decoy | known | semantic.aggregate_reconciliation_break | semantic.aggregate_reconciliation_break | correct | yes | ok | 9/9 | 11 | $0.148 |
| INC-H23 | per_capita_republished_monthly | known | semantic.unit_change | semantic.unit_change | correct | yes | ok | 8/8 | 7 | $0.103 |
| INC-H24 | renamed_duplicates_without_run_artifacts | known | integrity.duplicate_records | integrity.duplicate_records | correct | yes | ok | 10/10 | 16 | $0.207 |
| INC-H25 | upstream_adds_measures | known | schema.additive_drift | schema.additive_drift | correct | yes | ok | 8/8 | 13 | $0.159 |
| INC-H26 | suppression_marker_changed | known | values.type_format_drift | values.type_format_drift | correct | yes | ok | 7/7 | 7 | $0.111 |
| INC-H27 | engine_killed_with_new_column | novel | abstain | (abstained) | correct | - | ok | 6/6 | 9 | $0.117 |
| INC-C12 | legacy_duplicate_patient | known | integrity.duplicate_records | integrity.duplicate_records | correct | yes | ok | 7/7 | 9 | $0.110 |
| INC-C13 | orphan_condition_without_task_log | known | referential.orphan_reference | referential.orphan_reference | correct | yes | ok | 7/7 | 10 | $0.094 |
| INC-C14 | versioned_references | known | values.type_format_drift | values.type_format_drift | correct | yes | ok | 8/8 | 10 | $0.116 |

## Misses

- **INC-H21** (silent_rate_base_change_behind_new_columns): wrong; The new CMS Geographic Variation release (2026-10-15) has 4 telehealth columns that were not in the previous accepted release (fixture-2026-05-15): BENES_TELEHEALTH_PCT, TELEHEALTH_EVNTS_PER_1000_BENES, TELEHEALTH_MDCR_PYMT_AMT and TELEHEALTH_MDCR_PYMT_PC. No columns were removed and no renames were detected. The column count went from 246 to 250, and the row count (583) and suppression rate (0.051458) are the same as last time. The contract policy says unknown columns raise a warning, not a block, so the validate step warned and the run went on to publish. Every dbt test passed except assert_analysis_cohort_is_substantial, a warning that also fired on the previous published run, so it is unrelated. This run's output is what consumers see now. The new columns are not in the contract, so I assume nothing downstream reads them yet, but I did not check the transformation code.
