from __future__ import annotations

from pathlib import Path

from drc import evaluation
from drc.agents.baseline import BaselineInvestigator

GATES = Path(__file__).resolve().parents[1] / "eval" / "gates" / "baseline.yml"


def test_baseline_meets_its_regression_gates():
    result = evaluation.run(BaselineInvestigator())
    assert evaluation.check_gates(result["metrics"], GATES) == []
    # The playbook was written for hcip; the clinical pipeline is the transfer test.
    assert result["metrics"]["diagnosis_accuracy_known_clinical_etl"] < 0.5


def test_novel_incidents_penalize_confident_root_causes():
    label = {
        "scenario": "x",
        "split": "novel",
        "expected": "abstain",
        "acceptable": ["infra.compute_failure"],
        "impact": "previous_version_served",
        "actions": [],
    }
    from drc.models import Diagnosis, Incident, Investigation

    incident = Incident(
        incident_id="I",
        platform="hcip",
        pipeline="p",
        run_id="r",
        detected_at="t",
        signal="run_blocked",
        headline="h",
    )

    def case(status, category):
        d = Diagnosis(status=status, category=category, summary="", confidence=0.5)
        return evaluation.score_case(label, Investigation(incident=incident, investigator="t", diagnosis=d))

    assert case("abstained", None)["outcome"] == "correct"
    assert case("diagnosed", "infra.compute_failure")["outcome"] == "correct"
    assert case("diagnosed", "semantic.unit_change")["outcome"] == "wrong"


def test_spend_cap_stops_starting_investigations_before_the_limit():
    class PricedBaseline(BaselineInvestigator):
        name = "priced"

        def investigate(self, bundle, catalog, tracer=None):
            investigation = super().investigate(bundle, catalog, tracer)
            investigation.usage.cost_usd = 0.5
            return investigation

    ids = ["INC-H01", "INC-H02", "INC-H03", "INC-H04", "INC-H05"]
    result = evaluation.run(PricedBaseline(), incident_ids=ids, max_cost_usd=1.2)
    assert result["metrics"]["incidents"] == 2
    assert result["metrics"]["total_cost_usd"] == 1.0
    assert result["skipped_by_spend_cap"] == ["INC-H03", "INC-H04", "INC-H05"]
    assert "3 skipped by the spend cap" in evaluation.render_markdown(result)
