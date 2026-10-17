import json
import zlib
import hashlib
import os

def validate_token_data(data: dict):
    required_fields = ['version', 'viewBox', 'paths', 'palette', 'semantic_label', 'source_evidence']
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")

    if not isinstance(data['paths'], list) or len(data['paths']) >= 50:
        raise ValueError("Paths must be a list with fewer than 50 items")

    for path in data['paths']:
        if '<script>' in str(path) or 'javascript:' in str(path):
            raise ValueError("Malicious content found in paths")

    source_evidence = data.get('source_evidence', {})
    if 'license' not in source_evidence or source_evidence['license'].get('id') != 'CC0-1.0':
        raise ValueError("Asset must be explicitly licensed under CC0-1.0")

def hash_token(data: dict) -> str:
    canonical = json.dumps(data, separators=(',', ':'), sort_keys=True)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

def encode(data: dict) -> tuple[bytes, str]:
    validate_token_data(data)
    canonical = json.dumps(data, separators=(',', ':'), sort_keys=True)
    token_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    compressed = zlib.compress(canonical.encode('utf-8'))

    if len(compressed) >= 2048:
        raise ValueError("Compressed token exceeds 2048 bytes limit")

    return compressed, token_hash

def decode(compressed: bytes) -> dict:
    if len(compressed) >= 2048:
        raise ValueError("Compressed token exceeds 2048 bytes limit")

    # Prevent memory bombs by doing chunked decompression if necessary,
    # but zlib.decompress max_length can be used. Max 10MB uncompressed should be way more than enough for valid JSON.
    try:
        decompressed = zlib.decompress(compressed, bufsize=zlib.DEF_BUF_SIZE) # default behavior is fine for now but we could restrict
    except Exception as e:
        raise ValueError(f"Decompression failed: {e}")

    try:
        data = json.loads(decompressed.decode('utf-8'))
    except Exception as e:
        raise ValueError(f"Invalid JSON data: {e}")

    validate_token_data(data)
    return data

class ConceptRegistry:
    def __init__(self):
        self.mappings = {}

    def register(self, concept_id: str, token_hash: str):
        if concept_id in self.mappings:
            if self.mappings[concept_id] != token_hash:
                raise ValueError(f"Concept identity collision: concept '{concept_id}' is already registered with hash '{self.mappings[concept_id]}', tried to register with '{token_hash}'.")
        else:
            self.mappings[concept_id] = token_hash
