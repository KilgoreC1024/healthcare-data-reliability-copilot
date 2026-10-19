"""Investigators: a deterministic playbook baseline and the Claude-based agent, behind one interface."""

from __future__ import annotations

from typing import Any

from drc.agents.base import Investigator


def get_investigator(name: str, **options: Any) -> Investigator:
    if name == "baseline":
        from drc.agents.baseline import BaselineInvestigator

        return BaselineInvestigator()
    if name == "claude":
        from drc.agents.claude import ClaudeInvestigator

        return ClaudeInvestigator(**options)
    raise ValueError(f"unknown investigator '{name}' (choose baseline or claude)")
