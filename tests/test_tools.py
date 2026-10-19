from __future__ import annotations

import json

from drc.tools import MAX_OUTPUT_CHARS, TOOL_NAMES, TOOL_SPECS, ToolRegistry


def _out(record):
    assert not record.is_error, record.output
    return json.loads(record.output)


def test_tool_schemas_are_strict_compatible():
    for spec in TOOL_SPECS:
        schema = spec["input_schema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_every_tool_runs_on_every_incident_without_error(load):
    from drc.lab import store

    for incident_id in store.list_incidents():
        bundle, catalog = load(incident_id)
        reg = ToolRegistry(bundle, catalog, budget=100)
        source = catalog.sources[0]
        reg.call("get_run_overview", {})
        reg.call("list_failed_checks", {"include_warnings": True})
        reg.call("get_data_contract", {"source": source, "columns": []})
        reg.call("compare_schema", {"source": source})
        reg.call("profile_columns", {"source": source, "columns": []})
        reg.call("get_release_history", {"source": source})
        reg.call("get_downstream_impact", {"node": source})
        reg.call("search_runbook", {"query": "contract blocked"})
        reg.call("get_logs", {"name": ""})
        errors = [c for c in reg.calls if c.is_error and not c.output.startswith("Error: no schema recorded")]
        assert not errors, (incident_id, [(c.name, c.output) for c in errors])
        assert all(len(c.output) <= MAX_OUTPUT_CHARS + 60 for c in reg.calls)


def test_unknown_tools_are_refused_and_recorded(load):
    reg = ToolRegistry(*load("INC-H01"))
    record = reg.call("drop_table", {"table": "gold.mart_state_year"})
    assert record.is_error and "not an available tool" in record.output
    assert reg.guardrail_events == ["refused unknown tool 'drop_table'"]
    assert "drop_table" not in TOOL_NAMES


def test_tool_budget_is_enforced(load):
    reg = ToolRegistry(*load("INC-H01"), budget=2)
    reg.call("get_run_overview", {})
    reg.call("get_run_overview", {})
    third = reg.call("get_run_overview", {})
    assert third.is_error and "budget exhausted" in third.output


def test_compare_schema_spots_a_rename(load):
    out = _out(ToolRegistry(*load("INC-H02")).call("compare_schema", {"source": "cdc_places_county"}))
    assert out["removed"] == ["LocationID"] and out["added"] == ["Location_ID"]
    assert out["likely_renames"][0]["added"] == "Location_ID"


def test_profile_overview_surfaces_a_unit_change(load):
    out = _out(
        ToolRegistry(*load("INC-H12")).call("profile_columns", {"source": "cms_geo_variation", "columns": []})
    )
    top = out["columns_with_notable_changes"][0]
    assert top["column"] == "TOT_MDCR_PYMT_PC"
    assert round(top["previous"]["mean"] / top["current"]["mean"]) == 1000


def test_list_failed_checks_marks_persisting_warnings(load):
    out = _out(ToolRegistry(*load("INC-H13")).call("list_failed_checks", {"include_warnings": True}))
    flags = {c["check_name"]: c.get("also_warned_on_previous_published_run") for c in out["checks"]}
    assert flags == {"warn_rows_in_quarantine": False, "assert_analysis_cohort_is_substantial": True}


def test_audit_failure_details_include_the_failing_rows(load):
    out = _out(
        ToolRegistry(*load("INC-H11")).call(
            "get_check_details", {"check_name": "assert_county_totals_reconcile_to_state", "source": ""}
        )
    )
    assert out["failing_rows"][0]["state_fips"] == "42"
    assert out["failing_rows"][0]["beneficiary_ratio"] > 1.1


def test_downstream_impact_reaches_consumers(load):
    out = _out(ToolRegistry(*load("INC-H01")).call("get_downstream_impact", {"node": "cms_geo_variation"}))
    assets = {d["asset"] for d in out["downstream"]}
    assert {"silver_cms_geo_variation", "mart_county_cost_health"} <= assets
    assert any("dashboard" in c["name"].lower() for c in out["consumers"])
    assert out["currently_served"]["this_run_is_served"] is False


def test_runbook_search_finds_the_relevant_section(load):
    out = _out(
        ToolRegistry(*load("INC-H11")).call("search_runbook", {"query": "audit reconciliation failure"})
    )
    assert any("audit" in r["section"].lower() for r in out["results"])


def test_clinical_tools_expose_the_named_record_and_reference_profile(load):
    reg = ToolRegistry(*load("INC-C01"))
    detail = _out(reg.call("get_check_details", {"check_name": "quality_gate.validate_tables", "source": ""}))
    assert detail["records_named_in_error"][0]["id"] == "enc-003"
    profile = _out(
        reg.call(
            "profile_columns", {"source": "synthetic_fhir_bundle", "columns": ["Encounter.subject.reference"]}
        )
    )
    assert profile["columns"]["Encounter.subject.reference"]["current"]["unresolved_references"] == 1
    assert profile["columns"]["Encounter.subject.reference"]["previous"]["unresolved_references"] == 0
