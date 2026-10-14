import json
import os
import jsonschema

class ValidationError(Exception):
    pass

class ProficiencyValidator:
    def __init__(self, standards_dir=None):
        if standards_dir is None:
            standards_dir = os.path.dirname(os.path.abspath(__file__))

        schema_path = os.path.join(standards_dir, 'metadata.schema.json')
        with open(schema_path, 'r') as f:
            self.schema = json.load(f)

        frameworks_path = os.path.join(standards_dir, 'frameworks.json')
        with open(frameworks_path, 'r') as f:
            self.frameworks_data = json.load(f)

        self.valid_sources = {source['source_id'] for source in self.frameworks_data.get('sources', [])}

    def validate(self, record):
        try:
            jsonschema.validate(instance=record, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            raise ValidationError(f"Schema validation failed: {e.message}")

        status = record.get('status')
        source_identity = record.get('source_identity')
        level = record.get('level')
        coarse_difficulty = record.get('coarse_difficulty')

        if status in ('verified', 'estimated'):
            if not source_identity:
                raise ValidationError("source_identity and evaluation_method are required for verified/estimated status")

        if source_identity:
            if source_identity not in self.valid_sources:
                raise ValidationError(f"Invented source identity: {source_identity}")

        if level != 'unknown' and status == 'verified':
            if not source_identity:
                raise ValidationError("CEFR levels cannot be verified without local evidence (source_identity)")

        # Check for conflicting labels
        if level != 'unknown' and coarse_difficulty != 'unknown':
            expected_difficulty = {
                'A1': 'beginner',
                'A2': 'beginner',
                'B1': 'intermediate',
                'B2': 'intermediate',
                'C1': 'advanced',
                'C2': 'advanced'
            }
            if expected_difficulty[level] != coarse_difficulty:
                raise ValidationError(f"Conflicting labels: {level} cannot have {coarse_difficulty} difficulty")
