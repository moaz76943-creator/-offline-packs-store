import json
import zlib
import hashlib
from typing import Dict, Any

def get_canonical_json(token_data: Dict[str, Any]) -> bytes:
    """Returns the canonical JSON representation of the token data."""
    return json.dumps(token_data, separators=(',', ':'), sort_keys=True).encode('utf-8')

def encode_token(token_data: Dict[str, Any]) -> bytes:
    """Encodes token data to canonical JSON and compresses with zlib."""
    json_bytes = get_canonical_json(token_data)
    compressed = zlib.compress(json_bytes)
    return compressed

def decode_token(compressed_bytes: bytes) -> Dict[str, Any]:
    """Decompresses zlib bytes and parses the JSON token data."""
    json_bytes = zlib.decompress(compressed_bytes)
    return json.loads(json_bytes.decode('utf-8'))

def calculate_hash(token_data: Dict[str, Any]) -> str:
    """Calculates SHA-256 hash from the canonical JSON representation."""
    json_bytes = get_canonical_json(token_data)
    return hashlib.sha256(json_bytes).hexdigest()
