import json
import jsonschema
from pathlib import Path
from typing import Dict, Any

class ProficiencyValidationError(ValueError):
    """Exception raised for validation errors in proficiency metadata."""
    pass

class ProficiencyValidator:
    def __init__(self, *, trusted_framework_mappings=None, approved_assignments=None):
        """External indices are independent proof, not taken from metadata being graded."""
        self.trusted_framework_mappings = trusted_framework_mappings or {}
        self.approved_assignments = approved_assignments or {}
        registry = Path(__file__).resolve().parents[2] / "catalog" / "language_registry.v1.json"
        self.languages = {entry["id"]: entry for entry in
                          json.loads(registry.read_text(encoding="utf-8"))["languages"]}
        self.schema_path = Path(__file__).parent / "metadata.schema.json"
        with self.schema_path.open(encoding="utf-8") as f:
            self.schema = json.load(f)

    def validate(self, metadata: Dict[str, Any]) -> None:
        """
        Validates proficiency metadata against the schema and applies
        additional business logic.
        """
        try:
            jsonschema.validate(instance=metadata, schema=self.schema)
        except jsonschema.ValidationError as e:
            raise ProficiencyValidationError(f"Schema validation failed: {e.message}")

        if metadata["label_status"] in ("verified", "estimated") and not metadata.get("source_evidence"):
            raise ProficiencyValidationError("Verified and estimated labels must have source evidence.")
        source_record = metadata.get("source_evidence")
        if source_record:
            if not isinstance(source_record.get("source_id"), str) or not source_record["source_id"].strip():
                raise ProficiencyValidationError("Source ID cannot be empty or whitespace.")
            if not isinstance(source_record.get("source_version"), str) or not source_record["source_version"].strip():
                raise ProficiencyValidationError("Source version cannot be empty or whitespace.")

        language = metadata["language"]
        language_record = self.languages.get(language)
        if language_record is None:
            raise ProficiencyValidationError("Language is not a canonical registered ID.")
        target_id = metadata["target_id"]
        cefr_level = metadata["cefr_level"]
        registry_proficiency = language_record.get("proficiency", {})
        if cefr_level != "unknown" and "CEFR" not in registry_proficiency.get("framework_ids", []):
            raise ProficiencyValidationError("CEFR assignment is not registered for this language.")
        expected = ("beginner" if cefr_level in ("A1", "A2")
                    else "intermediate" if cefr_level in ("B1", "B2")
                    else "advanced" if cefr_level in ("C1", "C2") else None)
        flags = metadata["coarse_difficulty"]
        if any(flags[k] != (k == expected) for k in ("beginner", "intermediate", "advanced")):
            raise ProficiencyValidationError("CEFR level and coarse difficulty disagree.")
        if metadata["label_status"] == "verified":
            if (registry_proficiency.get("mapping_status") != "mapped"
                    and self.trusted_framework_mappings.get(language) != "CEFR"):
                raise ProficiencyValidationError("Language has no reviewed CEFR framework mapping.")
            evidence = metadata.get("source_evidence") or {}
            proof = self.approved_assignments.get(evidence.get("source_id"))
            if (not isinstance(proof, dict)
                    or proof.get("language") != language
                    or proof.get("target_id") != target_id
                    or proof.get("classification_target") != metadata["classification_target"]
                    or proof.get("source_version") != evidence.get("source_version")
                    or proof.get("cefr_level") != cefr_level
                    or proof.get("review_status") != "approved"):
                raise ProficiencyValidationError("Verified assignment lacks independently approved language/target/level evidence.")

        label_status = metadata.get("label_status")
        cefr_level = metadata.get("cefr_level")
        evaluation_method = metadata.get("evaluation_method")
        source_evidence = metadata.get("source_evidence")

        if label_status in ("verified", "estimated"):
            if not source_evidence:
                raise ProficiencyValidationError("Verified and estimated labels must have source evidence.")
            if not evaluation_method or evaluation_method == "unknown":
                raise ProficiencyValidationError("Verified and estimated labels must specify an evaluation method.")
            if label_status == "verified" and evaluation_method != "published_content_assignment":
                raise ProficiencyValidationError("Verified label requires 'published_content_assignment' evaluation method.")
            if label_status == "estimated" and evaluation_method != "descriptor_guided_review":
                raise ProficiencyValidationError("Estimated label requires 'descriptor_guided_review' evaluation method.")

        # Rule: Avoid treating CEFR as an automatically validated standard for every language
        # without suitable local evidence. This could imply verified labels need specific checks,
        # but generic local evidence requirements can be strictly handled by source_evidence checks above.

        if label_status == "unverified":
            if cefr_level != "unknown":
                raise ProficiencyValidationError("Unverified status must have cefr_level as 'unknown'.")
