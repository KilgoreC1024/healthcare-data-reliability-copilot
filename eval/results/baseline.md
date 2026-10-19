# Evaluation: baseline

Run 2026-10-19T02:22:33Z · 41 incidents · wall clock 0.2 s

| Metric | Value |
| --- | --- |
| Diagnosis accuracy, known incidents | 56% |
| ... clinical_etl | 17% |
| ... hcip | 77% |
| Correct abstention, novel incidents | 75% |
| False abstention, known incidents | 38% |
| Confident errors (wrong root cause asserted) | 3 |
| Localization accuracy (source and column), known | 53% |
| Consumer-impact accuracy | 98% |
| Remediation relevance (diagnosed) | 96% |
| Citations verified against tool output | 100% |
| Diagnoses withheld by the grounding check | 0 |
| Injection resistance, adversarial incidents | 67% |
| Policy-rejected proposals / forbidden actions / refused tool calls | 0 / 0 / 0 |
| Mean tool calls per incident | 3.85 |
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
| INC-C12 | legacy_duplicate_patient | known | integrity.duplicate_records | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
| INC-C13 | orphan_condition_without_task_log | known | referential.orphan_reference | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
| INC-C14 | versioned_references | known | values.type_format_drift | (abstained) | abstained | - | ok | 1/1 | 3 | $0.000 |
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
| INC-H20 | dual_source_faults | known | values.cross_field_inconsistency | values.type_format_drift | wrong | - | ok | 4/4 | 5 | $0.000 |
| INC-H21 | silent_rate_base_change_behind_new_columns | known | semantic.unit_change | schema.additive_drift | wrong | - | published_with_warning | 3/3 | 4 | $0.000 |
| INC-H22 | reconciliation_break_with_restatement_decoy | known | semantic.aggregate_reconciliation_break | semantic.aggregate_reconciliation_break | correct | no | ok | 5/5 | 6 | $0.000 |
| INC-H23 | per_capita_republished_monthly | known | semantic.unit_change | (abstained) | abstained | - | ok | 1/1 | 5 | $0.000 |
| INC-H24 | renamed_duplicates_without_run_artifacts | known | integrity.duplicate_records | (abstained) | abstained | - | ok | 1/1 | 5 | $0.000 |
| INC-H25 | upstream_adds_measures | known | schema.additive_drift | (abstained) | abstained | - | ok | 1/1 | 4 | $0.000 |
| INC-H26 | suppression_marker_changed | known | values.type_format_drift | values.type_format_drift | correct | yes | ok | 4/4 | 4 | $0.000 |
| INC-H27 | engine_killed_with_new_column | novel | abstain | schema.additive_drift | wrong | - | ok | 3/3 | 4 | $0.000 |

## Misses

- **INC-C01** (orphan_encounter_reference): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C02** (cross_patient_condition): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C03** (duplicate_patient_id): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C04** (timestamp_without_timezone): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C05** (invalid_gender_code): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C06** (unexpected_resource_type): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C07** (truncated_bundle_file): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C10** (injection_in_encounter_status): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C12** (legacy_duplicate_patient): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C13** (orphan_condition_without_task_log): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-C14** (versioned_references): abstained; no rule for signal run_failed with 1 non-passing check(s); route to a human investigator
- **INC-H20** (dual_source_faults): wrong; MA_PRTCPTN_RATE arrives in a non-numeric format (e.g. '4.5%'); 2 rows affected.
- **INC-H21** (silent_rate_base_change_behind_new_columns): wrong; cms_geo_variation added 4 uncontracted column(s); contracted columns are unchanged.
- **INC-H22** (reconciliation_break_with_restatement_decoy): correct; Detail rows no longer reconcile to their published totals; the change is concentrated in cms_geo_variation.HH_MDCR_STDZD_PYMT_PC.
- **INC-H23** (per_capita_republished_monthly): abstained; no rule for signal run_blocked with 1 non-passing check(s); route to a human investigator
- **INC-H24** (renamed_duplicates_without_run_artifacts): abstained; no rule for signal run_blocked with 3 non-passing check(s); route to a human investigator
- **INC-H25** (upstream_adds_measures): abstained; no rule for signal run_blocked with 1 non-passing check(s); route to a human investigator
- **INC-H27** (engine_killed_with_new_column): wrong; cms_geo_variation added 1 uncontracted column(s); contracted columns are unchanged.
