import json
import os
from jsonschema import validate, ValidationError as JsonSchemaValidationError

class ValidationError(Exception):
    pass

class ProficiencyValidator:
    def __init__(self):
        base_dir = os.path.dirname(__file__)
        schema_path = os.path.join(base_dir, 'metadata.schema.json')
        frameworks_path = os.path.join(base_dir, 'frameworks.json')

        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

        with open(frameworks_path, 'r', encoding='utf-8') as f:
            self.frameworks_data = json.load(f)
            self.valid_source_ids = {source['source_id'] for source in self.frameworks_data.get('sources', [])}

    def validate(self, instance):
        try:
            validate(instance=instance, schema=self.schema)
        except JsonSchemaValidationError as e:
            raise ValidationError(f"Schema validation error: {e.message}")

        # Check source identity
        source_identity = instance.get('source_identity')
        if source_identity and source_identity not in self.valid_source_ids:
            raise ValidationError(f"Invalid source_identity: {source_identity}")

        # Check conflicting difficulty labels
        level = instance.get('level')
        coarse = instance.get('coarse_difficulty')

        # A simple non-conflicting logic mapping
        if level != "unknown" and coarse != "unknown":
            if level in ["A1", "A2"] and coarse != "beginner":
                raise ValidationError(f"Conflicting difficulty: {level} should be beginner")
            if level in ["B1", "B2"] and coarse != "intermediate":
                raise ValidationError(f"Conflicting difficulty: {level} should be intermediate")
            if level in ["C1", "C2"] and coarse != "advanced":
                raise ValidationError(f"Conflicting difficulty: {level} should be advanced")

        # Check CEFR local evidence requirement
        if level in ["A1", "A2", "B1", "B2", "C1", "C2"] and instance.get('status') == 'verified':
            evidence = instance.get('evidence', {})
            if not evidence.get('local_evidence', False):
                 raise ValidationError("CEFR verified status requires suitable local evidence")

        return True
