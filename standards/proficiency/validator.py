import json
from pathlib import Path
from typing import Any
import jsonschema

# We will reuse the valid existing definitions from the main mapping engine API rather than an arbitrary `frameworks.json` open method.
# Wait, `frameworks.json` *does* exist in `standards/proficiency/` as seen before.
# It has "schema_version", "frameworks", and "sources".

ROOT = Path(__file__).resolve().parent

class ValidationError(ValueError):
    """Validation error for proficiency metadata."""
    pass

class ProficiencyValidator:
    def __init__(self):
        with (ROOT / "metadata.schema.json").open("r", encoding="utf-8") as f:
            self.schema = json.load(f)

        # Load exactly the existing conventions and vocabulary for sources from `frameworks.json` in the same directory.
        with (ROOT / "frameworks.json").open("r", encoding="utf-8") as f:
            frameworks_data = json.load(f)

        self.sources = {source["source_id"]: source for source in frameworks_data.get("sources", [])}

        self.cefr_to_coarse = {
            "A1": "beginner",
            "A2": "beginner",
            "B1": "intermediate",
            "B2": "intermediate",
            "C1": "advanced",
            "C2": "advanced",
            "unknown": "unknown"
        }

    def validate_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        try:
            jsonschema.validate(instance=metadata, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            raise ValidationError(f"Schema validation failed: {e.message}")

        self._validate_classification(metadata["entry_level_classification"])
        self._validate_classification(metadata["example_level_classification"])

        return metadata

    def _validate_classification(self, classification: dict[str, Any]) -> None:
        status = classification["classification_status"]
        cefr = classification["cefr_level"]
        coarse = classification["coarse_difficulty"]
        source_id = classification.get("source_identity")

        # Require source identity for verified CEFR levels to prevent treating CEFR
        # as automatically verified standard without suitable local evidence.
        if status == "verified" and cefr != "unknown":
            if not source_id:
                raise ValidationError("source_identity is required for verified CEFR levels")
            if source_id not in self.sources:
                raise ValidationError(f"Invalid or invented source_identity: {source_id}")

        if source_id is not None and source_id not in self.sources:
            raise ValidationError(f"Invalid or invented source_identity: {source_id}")

        # Check for conflicting difficulty labels
        if cefr != "unknown" and coarse != "unknown":
            expected_coarse = self.cefr_to_coarse.get(cefr)
            if coarse != expected_coarse:
                raise ValidationError(f"Conflicting difficulty labels: {cefr} does not match {coarse}")

        if status in ("unknown", "unverified"):
            if cefr != "unknown" or coarse != "unknown":
                raise ValidationError(f"Cannot claim difficulty for {status} status")
