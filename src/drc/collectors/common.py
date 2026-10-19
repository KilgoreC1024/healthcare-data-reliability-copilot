"""Helpers shared by collectors."""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@cache
def platform_registry() -> dict[str, Any]:
    return yaml.safe_load(resources.files("drc").joinpath("platforms.yml").read_text(encoding="utf-8"))


def strip_ansi(text: str) -> str:
    return ANSI.sub("", text)


def tail(text: str, lines: int) -> str:
    return "\n".join(text.splitlines()[-lines:])


def sig(value: float | None, digits: int = 6) -> float | int | None:
    """Round to significant digits so recorded numbers stay compact and stable across runs."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if value == 0:
        return 0
    rounded = round(value, digits - 1 - int(math.floor(math.log10(abs(value)))))
    return int(rounded) if float(rounded).is_integer() and abs(rounded) < 1e15 else rounded


def jsonable(value: Any) -> Any:
    """Convert database values into plain JSON types (timestamps become ISO strings)."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return sig(value)
    return value


def maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def markdown_sections(doc: str, text: str, max_chars: int = 2500) -> list[dict[str, str]]:
    """Split a Markdown document into heading-scoped sections for retrieval."""
    sections: list[dict[str, str]] = []
    title, buffer = "(introduction)", []
    for line in text.splitlines():
        if re.match(r"^#{1,4} ", line):
            if "".join(buffer).strip():
                sections.append({"doc": doc, "section": title, "text": "\n".join(buffer).strip()[:max_chars]})
            title, buffer = line.lstrip("#").strip(), []
        else:
            buffer.append(line)
    if "".join(buffer).strip():
        sections.append({"doc": doc, "section": title, "text": "\n".join(buffer).strip()[:max_chars]})
    return sections


def load_knowledge(project_root: Path, docs: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for doc in docs:
        path = project_root / doc
        if path.is_file():
            out.extend(markdown_sections(doc, path.read_text(encoding="utf-8")))
    return out
