"""Stdlib-only proficiency metadata gate.

Classified CEFR labels require an A1–C2 level. Verified labels also require an
independently approved assignment. Estimated labels require either that same
assignment or a source identity and version already present in frameworks.json.
Neither path treats the submitted metadata as its own proof.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

CLASSIFIED_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


class ProficiencyValidationError(ValueError):
    """Exception raised for validation errors in proficiency metadata."""


def _fail_schema(message: str) -> None:
    raise ProficiencyValidationError(f"Schema validation failed: {message}")


def _check_schema(value: Any, spec: dict, path: str = "$") -> None:
    """Interpret the keywords used by metadata.schema.json. No third-party package."""
    expected = spec.get("type")
    if isinstance(expected, str):
        expected = [expected]
    if expected and not any(_TYPES[kind](value) for kind in expected):
        _fail_schema(f"type mismatch at {path}")
    if "enum" in spec and value not in spec["enum"]:
        _fail_schema(f"unknown value at {path}")
    if isinstance(value, str):
        if len(value) < spec.get("minLength", 0):
            _fail_schema(f"text too short at {path}")
        pattern = spec.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            _fail_schema(f"invalid text at {path}")
        if spec.get("format") == "uri":
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                _fail_schema(f"invalid URI at {path}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in spec and value < spec["minimum"]:
            _fail_schema(f"numeric bound at {path}")
        if "maximum" in spec and value > spec["maximum"]:
            _fail_schema(f"numeric bound at {path}")
    if isinstance(value, dict):
        for key in spec.get("required", []):
            if key not in value:
                _fail_schema(f"missing {path}.{key}")
        properties = spec.get("properties", {})
        for key, child in value.items():
            if key not in properties:
                if spec.get("additionalProperties") is False:
                    _fail_schema(f"unexpected {path}.{key}")
                continue
            _check_schema(child, properties[key], f"{path}.{key}")


class ProficiencyValidator:
    def __init__(self, *, trusted_framework_mappings=None, approved_assignments=None,
                 trusted_sources=None):
        """External indices are independent proof, not taken from metadata being graded."""
        self.trusted_framework_mappings = trusted_framework_mappings or {}
        self.approved_assignments = approved_assignments or {}
        self._languages_cache = None
        self.schema_path = Path(__file__).parent / "metadata.schema.json"
        self.schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        if trusted_sources is None:
            catalog = json.loads((Path(__file__).parent / "frameworks.json").read_text(encoding="utf-8"))
            trusted_sources = {
                source["source_id"]: source
                for source in catalog.get("sources", [])
                if isinstance(source, dict) and isinstance(source.get("source_id"), str)
            }
        self.trusted_sources = trusted_sources

    def _get_languages(self) -> Dict[str, Any]:
        if self._languages_cache is None:
            root = Path(__file__).resolve().parents[2]
            registry = root / "catalog" / "language_registry.v1.json"
            try:
                with open(registry, "r", encoding="utf-8") as f:
                    self._languages_cache = {entry["id"]: entry for entry in json.load(f)["languages"]}
            except FileNotFoundError:
                raise ProficiencyValidationError("Language registry file is missing.")
        return self._languages_cache

    def _assignment_matches(self, metadata: Dict[str, Any], evidence: Dict[str, Any]) -> bool:
        proof = self.approved_assignments.get(evidence.get("source_id"))
        return (isinstance(proof, dict)
                and proof.get("language") == metadata["language"]
                and proof.get("target_id") == metadata["target_id"]
                and proof.get("classification_target") == metadata["classification_target"]
                and proof.get("source_version") == evidence.get("source_version")
                and proof.get("cefr_level") == metadata["cefr_level"]
                and proof.get("review_status") == "approved")

    def _catalog_source_matches(self, evidence: Dict[str, Any]) -> bool:
        source = self.trusted_sources.get(evidence.get("source_id"))
        return isinstance(source, dict) and source.get("version") == evidence.get("source_version")

    def validate(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Validate proficiency metadata against the schema and independent evidence."""
        try:
            if not isinstance(metadata, dict):
                _fail_schema("metadata must be an object")
            _check_schema(metadata, self.schema)

            label_status = metadata["label_status"]
            cefr_level = metadata["cefr_level"]
            source_record = metadata.get("source_evidence")
            if label_status in ("verified", "estimated") and not source_record:
                raise ProficiencyValidationError("Verified and estimated labels must have source evidence.")
            if source_record:
                if not isinstance(source_record.get("source_id"), str) or not source_record["source_id"].strip():
                    raise ProficiencyValidationError("Source ID cannot be empty or whitespace.")
                if not isinstance(source_record.get("source_version"), str) or not source_record["source_version"].strip():
                    raise ProficiencyValidationError("Source version cannot be empty or whitespace.")

            language = metadata["language"]
            language_record = self._get_languages().get(language)
            if language_record is None:
                raise ProficiencyValidationError("Language is not a canonical registered ID.")
            if label_status in ("verified", "estimated") and cefr_level not in CLASSIFIED_LEVELS:
                raise ProficiencyValidationError("Classified labels require an A1-C2 CEFR level.")

            target_id = metadata["target_id"]
            registry_proficiency = language_record.get("proficiency", {})
            if cefr_level != "unknown" and "CEFR" not in registry_proficiency.get("framework_ids", []):
                raise ProficiencyValidationError("CEFR assignment is not registered for this language.")
            expected = ("beginner" if cefr_level in ("A1", "A2")
                        else "intermediate" if cefr_level in ("B1", "B2")
                        else "advanced" if cefr_level in ("C1", "C2") else None)
            flags = metadata["coarse_difficulty"]
            if any(flags[k] != (k == expected) for k in ("beginner", "intermediate", "advanced")):
                raise ProficiencyValidationError("CEFR level and coarse difficulty disagree.")

            evaluation_method = metadata.get("evaluation_method")
            if label_status in ("verified", "estimated"):
                if not evaluation_method or evaluation_method == "unknown":
                    raise ProficiencyValidationError("Verified and estimated labels must specify an evaluation method.")
                if label_status == "verified" and evaluation_method != "published_content_assignment":
                    raise ProficiencyValidationError("Verified label requires 'published_content_assignment' evaluation method.")
                if label_status == "estimated" and evaluation_method != "descriptor_guided_review":
                    raise ProficiencyValidationError("Estimated label requires 'descriptor_guided_review' evaluation method.")
                evidence = source_record or {}
                if label_status == "verified":
                    if (registry_proficiency.get("mapping_status") != "mapped"
                            and self.trusted_framework_mappings.get(language) != "CEFR"):
                        raise ProficiencyValidationError("Language has no reviewed CEFR framework mapping.")
                    if not self._assignment_matches(metadata, evidence):
                        raise ProficiencyValidationError(
                            "Verified assignment lacks independently approved language/target/level evidence.")
                elif not (self._catalog_source_matches(evidence) or self._assignment_matches(metadata, evidence)):
                    raise ProficiencyValidationError(
                        "Estimated assignment lacks a trusted catalog source or independently approved evidence.")

            if label_status == "unverified" and cefr_level != "unknown":
                raise ProficiencyValidationError("Unverified status must have cefr_level as 'unknown'.")

        except ProficiencyValidationError as e:
            return {"status": "REJECT", "issues": [str(e)]}

        return {"status": "ACCEPT", "issues": []}
