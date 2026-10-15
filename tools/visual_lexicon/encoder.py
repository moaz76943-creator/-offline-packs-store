import json
import zlib
import hashlib
from typing import Tuple
from .validator import TokenValidator, ValidationError

class TokenEncoder:
    MAX_BYTES = 2048

    @classmethod
    def encode(cls, token: dict) -> Tuple[bytes, str]:
        """
        Validates, canonicalizes, hashes, and compresses a token.
        Returns a tuple of (compressed_bytes, sha256_hash).
        """
        TokenValidator.validate(token)

        # Canonical JSON: sorted keys, no spaces
        canonical_json = json.dumps(token, sort_keys=True, separators=(',', ':'))
        canonical_bytes = canonical_json.encode('utf-8')

        # Deterministic SHA-256 hash
        sha256_hash = hashlib.sha256(canonical_bytes).hexdigest()

        # Zlib compress
        compressed_bytes = zlib.compress(canonical_bytes)

        # Enforce byte limit
        if len(compressed_bytes) > cls.MAX_BYTES:
            raise ValueError(f"Token exceeds max size: {len(compressed_bytes)} > {cls.MAX_BYTES} bytes")

        return compressed_bytes, sha256_hash
