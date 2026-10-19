"""Reading and writing the benchmark: incident bundles, platform catalogs, and labels."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from drc.models import Catalog, IncidentBundle


def benchmark_root() -> Path:
    env = os.environ.get("DRC_BENCHMARK")
    if env:
        return Path(env)
    for candidate in (Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parents[3]):
        if (candidate / "benchmark" / "labels.yml").is_file():
            return candidate / "benchmark"
    return Path.cwd() / "benchmark"


def redact(value: Any, replacements: list[tuple[str, str]]) -> Any:
    """Apply literal replacements to every string in a nested structure (keys included)."""
    if isinstance(value, dict):
        return {redact(k, replacements): redact(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, replacements) for v in value]
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    return value


def path_replacements(path: Path, neutral: str) -> list[tuple[str, str]]:
    """Every spelling of a local path that can appear in logs, mapped to a neutral one."""
    resolved = path.resolve()
    forms = {str(resolved), resolved.as_posix(), str(path), path.as_posix()}
    forms |= {f.replace("\\", "\\\\") for f in list(forms)}
    return sorted(((f, neutral) for f in forms if f), key=lambda kv: -len(kv[0]))


def normalize_separators(value: Any, prefixes: tuple[str, ...]) -> Any:
    """After redaction, make paths under the neutral prefixes use single forward slashes."""
    if isinstance(value, dict):
        return {k: normalize_separators(v, prefixes) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_separators(v, prefixes) for v in value]
    if isinstance(value, str):
        for prefix in prefixes:
            if prefix in value:
                value = re.sub(
                    re.escape(prefix) + r"[^\s\"'()]*", lambda m: re.sub(r"[\\/]+", "/", m.group(0)), value
                )
    return value


def write_bundle(bundle: IncidentBundle, root: Path | None = None) -> Path:
    root = root or benchmark_root()
    path = root / "incidents" / f"{bundle.incident.incident_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bundle.model_dump(mode="json"), indent=1, sort_keys=False) + "\n", encoding="utf-8"
    )
    return path


def write_catalog(catalog: Catalog, root: Path | None = None) -> Path:
    root = root or benchmark_root()
    path = root / "catalog" / f"{catalog.platform}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog.model_dump(mode="json"), indent=1) + "\n", encoding="utf-8")
    return path


def load_bundle(incident_id_or_path: str, root: Path | None = None) -> IncidentBundle:
    path = Path(incident_id_or_path)
    if not path.is_file():
        path = (root or benchmark_root()) / "incidents" / f"{incident_id_or_path}.json"
    return IncidentBundle.model_validate_json(path.read_text(encoding="utf-8"))


def load_catalog(platform: str, root: Path | None = None) -> Catalog:
    path = (root or benchmark_root()) / "catalog" / f"{platform}.json"
    return Catalog.model_validate_json(path.read_text(encoding="utf-8"))


def list_incidents(root: Path | None = None) -> list[str]:
    return sorted(p.stem for p in ((root or benchmark_root()) / "incidents").glob("*.json"))


def load_labels(root: Path | None = None) -> dict[str, dict[str, Any]]:
    path = (root or benchmark_root()) / "labels.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["incidents"]
