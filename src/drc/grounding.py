"""Mechanical evidence verification (docs/adr/0002).

Every citation names a tool call and quotes text from that call's output. A citation is verified only
if the quote appears verbatim (after whitespace and JSON-escaping normalization) in the output of a
successful call made during *this* investigation. Nothing here asks a model whether the evidence is
convincing: it either is in the record or it is not.

A diagnosis with no verified citation is withheld (converted to an abstention) so an unsupported root
cause never reaches the on-call engineer as a conclusion.
"""

from __future__ import annotations

import re

from drc.models import Diagnosis, ToolCall

MIN_QUOTE_CHARS = 3


def _norm(text: str) -> str:
    text = text.replace('\\"', '"').replace("\\n", " ").replace("\\\\", "\\")
    return re.sub(r"\s+", " ", text).strip().lower()


def _loose(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'["\\]', "", text)).strip().lower()


def quote_in_output(quote: str, output: str) -> bool:
    q = _norm(quote).strip('"').strip()
    if len(q) < MIN_QUOTE_CHARS:
        return False
    return q in _norm(output) or _loose(q) in _loose(output)


def verify(diagnosis: Diagnosis, calls: list[ToolCall]) -> tuple[Diagnosis, list[str]]:
    by_id = {c.call_id: c for c in calls if not c.is_error}
    events: list[str] = []
    checked = []
    for citation in diagnosis.evidence:
        call = by_id.get(citation.tool_call_id)
        ok = call is not None and quote_in_output(citation.quote, call.output)
        if not ok:
            reason = "unknown or failed tool call" if call is None else "quote not found in the cited output"
            events.append(f"unverified citation ({reason}): {citation.tool_call_id} {citation.quote[:80]!r}")
        checked.append(citation.model_copy(update={"verified": ok}))
    result = diagnosis.model_copy(update={"evidence": checked})
    if result.status == "diagnosed" and not any(c.verified for c in checked):
        events.append("diagnosis withheld: no verified evidence")
        result = result.model_copy(
            update={
                "status": "abstained",
                "category": None,
                "abstain_reason": "withheld by the grounding check: none of the cited evidence could be verified "
                f"(original category: {result.category})",
            }
        )
    return result, events
