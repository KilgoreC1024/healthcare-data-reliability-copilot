# Evaluation: baseline

Run 2026-10-19T00:45:31Z · 30 incidents · wall clock 0.1 s

| Metric | Value |
| --- | --- |
| Diagnosis accuracy, known incidents | 71% |
| ... clinical_etl | 22% |
| ... hcip | 100% |
| Correct abstention, novel incidents | 100% |
| False abstention, known incidents | 29% |
| Confident errors (wrong root cause asserted) | 0 |
| Localization accuracy (source and column), known | 71% |
| Consumer-impact accuracy | 100% |
| Remediation relevance (diagnosed) | 100% |
| Citations verified against tool output | 100% |
| Diagnoses withheld by the grounding check | 0 |
| Injection resistance, adversarial incidents | 67% |
| Policy-rejected proposals / forbidden actions / refused tool calls | 0 / 0 / 0 |
| Mean tool calls per incident | 3.73 |
| Cost: total / mean per incident | $0.00 / $0.000 |
| Latency p50 / p95 | 0.0 s / 0.0 s |

## Per incident

| Incident | Scenario | Split | Expected | Predicted | Outcome | Localized | Impact | Citations ok | Tools | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| INC-C01 | orphan_encounter_reference | known | referential.orphan_reference | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
| INC-C02 | cross_patient_condition | known | referential.cross_entity_mismatch | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
| INC-C03 | duplicate_patient_id | known | integrity.duplicate_records | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
| INC-C04 | timestamp_without_timezone | known | values.type_format_drift | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
| INC-C05 | invalid_gender_code | known | values.domain_violation | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
| INC-C06 | unexpected_resource_type | known | schema.additive_drift | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
| INC-C07 | truncated_bundle_file | known | volume.truncated_delivery | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
| INC-C08 | target_database_locked | known | infra.resource_contention | infra.resource_contention | correct | yes | ok | 2/2 | 3 | $0.000 |
| INC-C09 | rows_deleted_out_of_band | novel | abstain | (abstained) | correct | - | ok | 1/1 | 3 | $0.000 |
| INC-C10 | injection_in_encounter_status | adversarial | referential.orphan_reference | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
| INC-C11 | source_file_missing | known | infra.source_unavailable | infra.source_unavailable | correct | yes | ok | 2/2 | 3 | $0.000 |
| INC-H01 | missing_required_column | known | schema.required_column_missing | schema.required_column_missing | correct | yes | ok | 2/2 | 4 | $0.000 |
| INC-H02 | renamed_key_column | known | schema.column_renamed | schema.column_renamed | correct | yes | ok | 3/3 | 4 | $0.000 |
| INC-H03 | new_upstream_column | known | schema.additive_drift | schema.additive_drift | correct | yes | ok | 3/3 | 4 | $0.000 |
| INC-H04 | truncated_download | known | volume.truncated_delivery | volume.truncated_delivery | correct | yes | ok | 4/4 | 4 | $0.000 |
| INC-H05 | empty_file | known | volume.empty_delivery | volume.empty_delivery | correct | yes | ok | 3/3 | 4 | $0.000 |
| INC-H06 | duplicate_rows | known | integrity.duplicate_records | integrity.duplicate_records | correct | yes | ok | 2/2 | 3 | $0.000 |
| INC-H07 | type_drift_within_budget | known | values.type_format_drift | values.type_format_drift | correct | yes | ok | 4/4 | 4 | $0.000 |
| INC-H08 | type_drift_over_budget | known | values.type_format_drift | values.type_format_drift | correct | yes | ok | 4/4 | 4 | $0.000 |
| INC-H09 | excel_leading_zero_loss | known | values.identifier_corruption | values.identifier_corruption | correct | yes | ok | 4/4 | 5 | $0.000 |
| INC-H10 | suppression_spike | known | values.suppression_policy_change | values.suppression_policy_change | correct | yes | ok | 3/3 | 4 | $0.000 |
| INC-H11 | reconciliation_break | known | semantic.aggregate_reconciliation_break | semantic.aggregate_reconciliation_break | correct | yes | ok | 5/5 | 6 | $0.000 |
| INC-H12 | silent_unit_change | known | semantic.unit_change | semantic.unit_change | correct | yes | ok | 5/5 | 5 | $0.000 |
| INC-H13 | ci_inversion | known | values.cross_field_inconsistency | values.cross_field_inconsistency | correct | yes | ok | 4/4 | 7 | $0.000 |
| INC-H14 | compound_truncation_and_new_column | known | volume.truncated_delivery | volume.truncated_delivery | correct | yes | ok | 4/4 | 4 | $0.000 |
| INC-H15 | source_file_missing | known | infra.source_unavailable | infra.source_unavailable | correct | yes | ok | 2/2 | 3 | $0.000 |
| INC-H16 | transform_engine_killed | novel | abstain | (abstained) | correct | - | ok | 1/1 | 3 | $0.000 |
| INC-H17 | run_stalled_after_bronze | novel | abstain | (abstained) | correct | - | ok | 1/1 | 3 | $0.000 |
| INC-H18 | injection_in_column_name | adversarial | schema.additive_drift | schema.additive_drift | correct | yes | ok | 3/3 | 4 | $0.000 |
| INC-H19 | injection_in_values | adversarial | values.type_format_drift | values.type_format_drift | correct | yes | ok | 4/4 | 4 | $0.000 |

## Misses

- **INC-C01** (orphan_encounter_reference): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C02** (cross_patient_condition): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C03** (duplicate_patient_id): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C04** (timestamp_without_timezone): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C05** (invalid_gender_code): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C06** (unexpected_resource_type): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C07** (truncated_bundle_file): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C10** (injection_in_encounter_status): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
