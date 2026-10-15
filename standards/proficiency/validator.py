import json
import os
import jsonschema

class ProficiencyValidator:
    def __init__(self):
        schema_path = os.path.join(os.path.dirname(__file__), "metadata.schema.json")
        with open(schema_path, "r") as f:
            self.schema = json.load(f)

        frameworks_path = os.path.join(os.path.dirname(__file__), "frameworks.json")
        with open(frameworks_path, "r") as f:
            frameworks_data = json.load(f)
            self.valid_sources = {source["source_id"] for source in frameworks_data.get("sources", [])}

    def validate(self, metadata: dict) -> bool:
        try:
            jsonschema.validate(instance=metadata, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            raise ValueError(f"Schema validation failed: {e.message}")

        if metadata["source_identity"] not in self.valid_sources:
            raise ValueError(f"Invalid source identity: {metadata['source_identity']}")

        if metadata["status"] == "verified" and metadata["source_identity"] == "COE-CEFR-2020":
            raise ValueError("CEFR cannot be treated as an automatically validated standard for every language without suitable local evidence.")

        if metadata["proficiency_level"] != "unknown" and metadata["coarse_difficulty"] != "unknown":
            level = metadata["proficiency_level"]
            difficulty = metadata["coarse_difficulty"]

            expected_difficulty = "unknown"
            if level in ("A1", "A2"):
                expected_difficulty = "beginner"
            elif level in ("B1", "B2"):
                expected_difficulty = "intermediate"
            elif level in ("C1", "C2"):
                expected_difficulty = "advanced"

            if difficulty != expected_difficulty:
                 raise ValueError(f"Conflicting difficulty: {level} should be {expected_difficulty}, not {difficulty}")

        return True
