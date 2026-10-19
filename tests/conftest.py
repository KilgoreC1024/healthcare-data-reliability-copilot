from __future__ import annotations

from pathlib import Path

import pytest

from drc.lab import store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _benchmark(monkeypatch):
    monkeypatch.setenv("DRC_BENCHMARK", str(ROOT / "benchmark"))


@pytest.fixture
def load():
    def _load(incident_id: str):
        bundle = store.load_bundle(incident_id)
        return bundle, store.load_catalog(bundle.incident.platform)

    return _load
