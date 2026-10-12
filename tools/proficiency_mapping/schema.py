"""Offline, deterministic, evidence-aware proficiency catalog and mapping API.

Only stdlib dependencies. Schema validation does not assert authenticity of a source;
attestation requires independent publisher/license review before adding a source.
"""
from __future__ import annotations

import json
from typing import Any
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "standards" / "proficiency"
MAX_RECORDS = 10000
MAX_MAPPINGS = 1000
SKILLS = {"reading": "receptive", "listening": "receptive", "writing": "productive", "speaking": "productive"}


class ValidationError(ValueError):
    """Fail-closed validation error."""


def read_json(name: str) -> dict:
    if name not in {"record.schema.json", "frameworks.json", "mappings.json", "pilot_fixtures.json", "curricula.json"}:
        raise ValidationError("Unknown catalog file")
    with (ROOT / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def _check(value: Any, spec: dict, defs: dict, path: str = "$") -> None:
    """Small strict interpreter for the JSON Schema keywords in record.schema.json."""
    if "$ref" in spec:
        ref = spec["$ref"]
        if not ref.startswith("#/$defs/") or ref[8:] not in defs:
            raise ValidationError(f"Invalid schema reference at {path}")
        return _check(value, defs[ref[8:]], defs, path)
    types = spec.get("type", [])
    if isinstance(types, str):
        types = [types]
    matches = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "null": lambda v: v is None,
    }
    if types and not any(matches[t](value) for t in types):
        raise ValidationError(f"Type mismatch at {path}")
    if "enum" in spec and value not in spec["enum"]:
        raise ValidationError(f"Unknown value at {path}")
    if isinstance(value, str):
        if len(value) < spec.get("minLength", 0) or not re.search(spec.get("pattern", r".*"), value):
            raise ValidationError(f"Invalid text at {path}")
    if isinstance(value, int) and not isinstance(value, bool) and value < spec.get("minimum", value):
        raise ValidationError(f"Numeric bound at {path}")
    if isinstance(value, dict):
        for key in spec.get("required", []):
            if key not in value:
                raise ValidationError(f"Missing {path}.{key}")
        properties = spec.get("properties", {})
        for key, child in value.items():
            if key not in properties:
                if spec.get("additionalProperties") is False:
                    raise ValidationError(f"Unexpected {path}.{key}")
            else:
                _check(child, properties[key], defs, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) > spec.get("maxItems", len(value)):
            raise ValidationError(f"Too many items at {path}")
        if spec.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise ValidationError(f"Duplicate item at {path}")
        for i, child in enumerate(value):
            _check(child, spec.get("items", {}), defs, f"{path}[{i}]")
