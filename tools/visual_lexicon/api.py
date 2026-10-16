import json
import os
import jsonschema
from typing import Dict, Any, List, Optional
from tools.visual_lexicon.codec import encode_token, decode_token, calculate_hash

class ConceptRegistry:
    def __init__(self, schema_path: str = 'tools/visual_lexicon/schema.json'):
        self.concepts: Dict[str, str] = {}
        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

    def validate_token_data(self, token_data: Dict[str, Any]) -> None:
        """Validates token data against JSON schema and structural rules."""
        try:
            jsonschema.validate(instance=token_data, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            raise ValueError(f"Schema validation failed: {e.message}")

        # Ensure license is valid
        license_val = token_data.get('source_evidence', {}).get('license')
        if license_val not in ['CC0', 'Public Domain']:
            raise ValueError("Token must have CC0 or Public Domain license")

        # Bounds checks
        paths = token_data.get('paths', [])
        if len(paths) > 50:
            raise ValueError("Token has too many paths (max 50)")

    def register_concept(self, token_data: Dict[str, Any]) -> bytes:
        """Registers a concept and returns compressed token bytes."""
        self.validate_token_data(token_data)

        compressed_bytes = encode_token(token_data)
        if len(compressed_bytes) > 2048:
            raise ValueError("Token is oversized (>2048 bytes)")

        concept_id = token_data['concept_id']
        token_hash = calculate_hash(token_data)

        if concept_id in self.concepts and self.concepts[concept_id] != token_hash:
            raise ValueError(f"Concept identity collision for {concept_id}")

        self.concepts[concept_id] = token_hash
        return compressed_bytes

    def load_concept(self, compressed_bytes: bytes) -> Dict[str, Any]:
        """Loads and validates a token from compressed bytes."""
        token_data = decode_token(compressed_bytes)
        self.validate_token_data(token_data)

        concept_id = token_data['concept_id']
        token_hash = calculate_hash(token_data)

        if concept_id in self.concepts and self.concepts[concept_id] != token_hash:
            raise ValueError(f"Concept identity collision for {concept_id}")

        return token_data

    def process_incremental_updates(self, incoming_tokens: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Processes a list of token dictionaries and records changes."""
        changes = {
            'added': [],
            'updated': [],
            'unchanged': [],
            'failed': []
        }
        for token_data in incoming_tokens:
            try:
                self.validate_token_data(token_data)
                compressed = encode_token(token_data)
                if len(compressed) > 2048:
                    raise ValueError("Token too large")

                concept_id = token_data['concept_id']
                token_hash = calculate_hash(token_data)

                if concept_id not in self.concepts:
                    self.concepts[concept_id] = token_hash
                    changes['added'].append(concept_id)
                elif self.concepts[concept_id] == token_hash:
                    changes['unchanged'].append(concept_id)
                else:
                    # Actually, if concept exists and hash is different, it's a collision
                    raise ValueError(f"Concept identity collision for {concept_id}")
            except Exception as e:
                changes['failed'].append({'concept_id': token_data.get('concept_id'), 'error': str(e)})

        return changes
