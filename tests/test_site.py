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
