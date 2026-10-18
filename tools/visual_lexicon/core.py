import json
import zlib
import hashlib
from typing import Dict, Any, Tuple
from tools.visual_lexicon.schema import validate_token

MAX_COMPRESSED_SIZE = 2048

def encode_token(token: Dict[str, Any]) -> Tuple[bytes, str]:
    """
    Serializes, validates, and compresses a declarative token JSON.
    Returns a tuple of (compressed_bytes, sha256_hash_of_json).
    """
    validate_token(token)

    # Deterministic JSON serialization
    serialized = json.dumps(token, separators=(',', ':'), sort_keys=True)
    json_bytes = serialized.encode('utf-8')

    # Calculate deterministic hash
    token_hash = hashlib.sha256(json_bytes).hexdigest()

    # Compress via zlib
    compressed = zlib.compress(json_bytes, level=9)

    # Enforce maximum size bound (under 2048 compressed bytes)
    if len(compressed) >= MAX_COMPRESSED_SIZE:
        raise ValueError(f"Token is too large: {len(compressed)} bytes compressed (limit is {MAX_COMPRESSED_SIZE - 1})")

    return compressed, token_hash

def decode_token(compressed_bytes: bytes) -> Dict[str, Any]:
    """
    Decompresses and returns the token from bytes.
    Validates after decoding.
    """
    try:
        json_bytes = zlib.decompress(compressed_bytes)
    except zlib.error as e:
        raise ValueError(f"Failed to decompress token: {e}")

    try:
        token = json.loads(json_bytes.decode('utf-8'))
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in token: {e}")

    validate_token(token)
    return token
