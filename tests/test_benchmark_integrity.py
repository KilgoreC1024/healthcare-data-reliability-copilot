"""The benchmark is only meaningful if it is complete, valid, and free of label leakage."""

from __future__ import annotations

import json
import re

from drc.lab import store
from drc.taxonomy import CATEGORIES, REMEDIATION_CATALOG


def test_every_incident_is_labeled_and_every_label_has_an_incident():
    assert set(store.list_incidents()) == set(store.load_labels())


def test_benchmark_covers_both_platforms_and_all_splits():
    labels = store.load_labels()
    assert {i[:5] for i in labels} == {"INC-H", "INC-C"}
    splits = [label["split"] for label in labels.values()]
    assert splits.count("known") >= 20
    assert splits.count("novel") >= 3
    assert splits.count("adversarial") >= 3


def test_labels_use_the_taxonomy_and_the_remediation_catalog():
    for incident_id, label in store.load_labels().items():
        if label["split"] == "novel":
            assert label["expected"] == "abstain", incident_id
            assert set(label.get("acceptable", [])) <= set(CATEGORIES), incident_id
        else:
            assert label["category"] in CATEGORIES, incident_id
        assert set(label["actions"]) <= set(REMEDIATION_CATALOG), incident_id
        assert set(label.get("forbidden", [])) <= set(REMEDIATION_CATALOG), incident_id


def test_bundles_and_catalogs_validate():
    for incident_id in store.list_incidents():
        bundle = store.load_bundle(incident_id)
        assert bundle.incident.incident_id == incident_id
        catalog = store.load_catalog(bundle.incident.platform)
        assert catalog.sources and catalog.knowledge


def test_no_label_leaks_into_any_incident_bundle():
    labels = store.load_labels()
    for incident_id in store.list_incidents():
        text = json.dumps(store.load_bundle(incident_id).model_dump(mode="json")).lower()
        for label in labels.values():
            assert label["scenario"].lower() not in text, (incident_id, label["scenario"])
        assert "chaos" not in text, incident_id
        assert "fault-injection" not in text and "fault_injection" not in text, incident_id


def test_no_local_paths_or_user_names_leak_into_the_benchmark():
    pattern = re.compile(r"[a-z]:[\\/]+users[\\/]+|appdata|/tmp/|temp[\\/]+drc-", re.I)
    for path in store.benchmark_root().rglob("*.json"):
        match = pattern.search(path.read_text(encoding="utf-8"))
        assert match is None, (path.name, match and match.group(0))


def test_the_fault_injection_answer_key_is_not_in_the_knowledge_base():
    for platform in ("hcip", "clinical_etl"):
        docs = {k["doc"] for k in store.load_catalog(platform).knowledge}
        assert not any("fault-injection" in d for d in docs)
