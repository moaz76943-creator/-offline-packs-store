import json
import jsonschema
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent

class VisualTokenValidator:
    def __init__(self):
        with open(BASE / 'schema.json', 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

    def validate(self, token_record):
        # 1. Schema Validation
        try:
            jsonschema.validate(instance=token_record, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            raise ValueError(f"Schema validation failed: {e.message}")

        # 2. Complexity Bounds
        paths = token_record.get('paths', [])
        if len(paths) > 100:
            raise ValueError(f"Too many paths: {len(paths)} (max 100)")

        for path in paths:
            d = path.get('d', '')
            if len(d) > 2048:
                raise ValueError(f"Path data too long: {len(d)} (max 2048)")

            # Basic SVG path command validation to prevent injection
            # Allow M, L, H, V, C, S, Q, T, A, Z (and lowercase)
            # Allow numbers, spaces, commas, negative signs, decimals
            valid_d_pattern = re.compile(r'^[MmLlHhVvCcSsQqTtAaZz0-9\s,\.\-]+$')
            if not valid_d_pattern.match(d):
                raise ValueError("Invalid characters in path data")

        return True
