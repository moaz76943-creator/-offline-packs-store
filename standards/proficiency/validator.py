import json
import jsonschema
from pathlib import Path
from typing import Dict, Any

class ProficiencyValidationError(ValueError):
    """Exception raised for validation errors in proficiency metadata."""
    pass

class ProficiencyValidator:
    def __init__(self):
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

        # Rule: Reject invented source identities.
        # This is basic enforcement; any specified source evidence must have a valid non-empty id.
        if source_evidence:
            if not source_evidence.get("source_id").strip():
                raise ProficiencyValidationError("Source ID cannot be empty or whitespace.")
            if not source_evidence.get("source_version").strip():
                raise ProficiencyValidationError("Source version cannot be empty or whitespace.")

        if label_status == "unverified":
            if cefr_level != "unknown":
                raise ProficiencyValidationError("Unverified status must have cefr_level as 'unknown'.")
