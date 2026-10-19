"""Root-cause taxonomy and remediation catalog.

The taxonomy is platform-agnostic on purpose: a duplicated county row in a CMS file and a duplicated
Patient id in a FHIR bundle are the same failure class, even though different checks catch them and
different policies decide whether they block. Severity and consumer impact are reported separately from
the category.

The remediation catalog is a closed set. An investigator may only *propose* actions from it, every
proposal needs a named human approver, and the copilot executes none of them (docs/adr/0006).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    id: str
    title: str
    definition: str


CATEGORIES: dict[str, Category] = {
    c.id: c
    for c in [
        Category(
            "schema.required_column_missing",
            "Required column missing",
            "A column the contract requires is absent from the delivery and nothing resembling it was added.",
        ),
        Category(
            "schema.column_renamed",
            "Column renamed upstream",
            "A required column disappeared and a column with a near-identical name appeared in the same delivery.",
        ),
        Category(
            "schema.additive_drift",
            "Additive schema drift",
            "The delivery contains a new column or entity type that the contract or transformation does not cover.",
        ),
        Category(
            "volume.truncated_delivery",
            "Truncated delivery",
            "The delivery is incomplete: far fewer rows than the previous accepted release, or a file cut off mid-write.",
        ),
        Category(
            "volume.empty_delivery",
            "Empty delivery",
            "The delivery has a valid structure but no data rows.",
        ),
        Category(
            "integrity.duplicate_records",
            "Duplicate records",
            "The same business key (grain or primary key) appears more than once.",
        ),
        Category(
            "values.type_format_drift",
            "Value format drift",
            "Values arrive in a representation the contract does not accept (thousands separators, 'N/A' strings, "
            "timestamps without a time zone) while the column itself is unchanged.",
        ),
        Category(
            "values.identifier_corruption",
            "Identifier corruption",
            "Identifier or code values were mangled (for example, leading zeros stripped by a spreadsheet tool).",
        ),
        Category(
            "values.domain_violation",
            "Value outside allowed domain",
            "Values are well formed but outside the allowed set or range (an unknown code, a negative count).",
        ),
        Category(
            "values.suppression_policy_change",
            "Suppression policy change",
            "The share of suppressed or masked values jumped relative to the previous release.",
        ),
        Category(
            "values.cross_field_inconsistency",
            "Cross-field inconsistency",
            "Fields within the same record contradict each other (for example, a confidence interval that does "
            "not bracket its estimate).",
        ),
        Category(
            "semantic.aggregate_reconciliation_break",
            "Aggregate reconciliation break",
            "Detail rows no longer add up to the published totals they roll up to.",
        ),
        Category(
            "semantic.unit_change",
            "Unit or scale change",
            "A measure was republished in different units or scale; values are internally consistent in type but "
            "off by a constant factor.",
        ),
        Category(
            "referential.orphan_reference",
            "Orphan reference",
            "A record references a parent record that does not exist in the delivery.",
        ),
        Category(
            "referential.cross_entity_mismatch",
            "Cross-entity mismatch",
            "References exist but disagree (for example, a condition and its encounter point at different patients).",
        ),
        Category(
            "infra.source_unavailable",
            "Source unavailable",
            "The pipeline could not obtain the delivery at all (missing file, unreachable endpoint).",
        ),
        Category(
            "infra.resource_contention",
            "Resource contention",
            "Another process held a lock on, or modified, a resource the run needed.",
        ),
        Category(
            "infra.compute_failure",
            "Compute failure",
            "A processing engine crashed, was killed, or ran out of resources, independent of the data.",
        ),
    ]
}

DATA_CATEGORIES = frozenset(c for c in CATEGORIES if not c.startswith("infra."))


@dataclass(frozen=True)
class Action:
    id: str
    description: str
    # The role that must approve the action. Every action needs an approver; there is no auto-approve.
    approver_role: str
    # Actions that change what consumers see are only valid when bad data actually reached them.
    changes_published_data: bool = False


REMEDIATION_CATALOG: dict[str, Action] = {
    a.id: a
    for a in [
        Action(
            "request_corrected_delivery",
            "Send the data provider the evidence and request a corrected delivery.",
            "data_owner",
        ),
        Action(
            "amend_data_contract",
            "Open a pull request that updates the data contract for an intended upstream change.",
            "data_owner",
        ),
        Action(
            "update_transformation",
            "Change parsing or transformation code to handle a new, legitimate input shape.",
            "platform_engineer",
        ),
        Action(
            "correct_source_records",
            "Ask the upstream system owner to correct specific records at the source.",
            "data_owner",
        ),
        Action(
            "review_quarantined_rows",
            "Review rows held in quarantine and decide whether to correct, accept, or drop them upstream.",
            "data_steward",
        ),
        Action(
            "rerun_pipeline",
            "Re-run the pipeline after the underlying cause is fixed.",
            "platform_engineer",
        ),
        Action(
            "restore_previous_version",
            "Re-point consumers to the last audited version (rollback).",
            "platform_engineer",
            changes_published_data=True,
        ),
        Action(
            "escalate_to_platform_oncall",
            "Hand the incident to the infrastructure on-call with the collected evidence.",
            "incident_commander",
        ),
        Action(
            "monitor_no_action",
            "No change now; watch the next run.",
            "data_owner",
        ),
    ]
}


def describe_categories() -> str:
    return "\n".join(f"- {c.id}: {c.definition}" for c in CATEGORIES.values())


def describe_actions() -> str:
    return "\n".join(f"- {a.id}: {a.description}" for a in REMEDIATION_CATALOG.values())
