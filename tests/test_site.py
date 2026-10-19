"""The demo site embeds recorded investigations, including planted injection text, as inert data."""

from __future__ import annotations

import json
import re

from drc import site
from drc.lab import store


def _embedded(html: str) -> dict:
    match = re.search(r'<script id="drc-data" type="application/json">(.*?)</script>', html, re.S)
    assert match, "data block missing"
    return json.loads(match.group(1))


def test_site_replays_every_incident(tmp_path):
    data = _embedded(site.build(tmp_path).read_text(encoding="utf-8"))
    assert [i["id"] for i in data["incidents"]] == store.list_incidents()
    # The playbook's published results must cover the whole benchmark, or the page has gaps.
    assert all("baseline" in i["results"] for i in data["incidents"])
    assert {i["release"] for i in data["incidents"]} == {1, 2}


def test_no_embedded_value_can_break_out_of_the_data_block(tmp_path):
    html = site.build(tmp_path).read_text(encoding="utf-8")
    block = html.split('<script id="drc-data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "<" not in block
    # The injection strings from the adversarial incidents are present, as data.
    assert "Ignore all previous instructions" in json.dumps(_embedded(html))


def test_runs_published_in_separate_files_are_merged(tmp_path):
    results = store.benchmark_root().parent / "eval" / "results"
    release1 = json.loads((results / "claude.json").read_text(encoding="utf-8"))
    later = {
        **release1,
        "started_at": "2026-10-20T00:00:00Z",
        "release": 2,
        "cases": [{**release1["cases"][0], "incident_id": "INC-H20"}],
        "investigations": [
            {
                **release1["investigations"][0],
                "incident": {**release1["investigations"][0]["incident"], "incident_id": "INC-H20"},
            }
        ],
    }
    out = tmp_path / "results"
    out.mkdir()
    for name in ("baseline.json", "claude.json"):
        (out / name).write_text((results / name).read_text(encoding="utf-8"), encoding="utf-8")
    (out / "claude-zz-test.json").write_text(json.dumps(later), encoding="utf-8")

    data = site.payload(results_dir=out)
    by_id = {i["id"]: i for i in data["incidents"]}
    assert "claude" in by_id["INC-H01"]["results"] and "claude" in by_id["INC-H20"]["results"]
    assert [r["release"] for r in data["runs"]["claude"]][-1] == 2
    assert len(data["runs"]["baseline"]) == 1
