import json
import zlib
import hashlib
from typing import Tuple
from .validator import TokenValidator, ValidationError

class TokenDecoder:
    @classmethod
    def decode(cls, compressed_bytes: bytes) -> Tuple[dict, str]:
        """
        Decompresses a payload, decodes the canonical JSON, and verifies the hash.
        Returns the decoded token and its SHA-256 hash.
        """
        try:
            canonical_bytes = zlib.decompress(compressed_bytes)
        except zlib.error as e:
            raise ValueError("Failed to decompress token") from e

        sha256_hash = hashlib.sha256(canonical_bytes).hexdigest()

        try:
            canonical_json = canonical_bytes.decode('utf-8')
            token = json.loads(canonical_json)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("Failed to decode JSON from token") from e

        TokenValidator.validate(token)

        return token, sha256_hash
