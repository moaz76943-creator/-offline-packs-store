import zlib
import json

class TokenValidationError(Exception):
    pass

class CompactVectorToken:
    ALLOWED_LICENSES = {"CC0-1.0", "PUBLIC-DOMAIN", "PUBLIC_DOMAIN_ZERO_COPYRIGHT"}

    def __init__(self, concept_id: str, version: int, source_hash: str, license: str, geometry_paths: list, encoded_size: int):
        self.concept_id = concept_id
        self.version = version
        self.source_hash = source_hash
        self.license = license
        self.geometry_paths = geometry_paths
        self.encoded_size = encoded_size

    @classmethod
    def from_bytes(cls, data: bytes):
        if len(data) >= 2048:
            raise TokenValidationError("Token size must be less than 2048 bytes")

        try:
            decompressed = zlib.decompress(data)
        except zlib.error:
            # Maybe it's uncompressed?
            try:
                decompressed = data
                json.loads(decompressed) # check if json
            except Exception:
                raise TokenValidationError("Invalid compression or format")

        try:
            payload = json.loads(decompressed)
        except json.JSONDecodeError:
            raise TokenValidationError("Malformed token JSON")

        # Validate structure
        if "version" not in payload:
            raise TokenValidationError("Unsupported encoding version")
        if payload.get("version") != 1:
            raise TokenValidationError("Unsupported encoding version")

        concept_id = payload.get("concept_id")
        version = payload.get("version")
        source_hash = payload.get("source_hash")
        license = payload.get("license")
        geometry_paths = payload.get("paths")

        if not concept_id or not source_hash or not license or not isinstance(geometry_paths, list):
            raise TokenValidationError("Missing required fields")

        if license not in cls.ALLOWED_LICENSES:
            raise TokenValidationError(f"Invalid license: {license}")

        if not all(isinstance(p, str) for p in geometry_paths):
            raise TokenValidationError("Malformed geometry paths")

        return cls(concept_id, version, source_hash, license, geometry_paths, len(data))

    def to_bytes(self) -> bytes:
        payload = {
            "concept_id": self.concept_id,
            "version": self.version,
            "source_hash": self.source_hash,
            "license": self.license,
            "paths": self.geometry_paths
        }
        data = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        compressed = zlib.compress(data)
        if len(compressed) >= 2048:
            raise TokenValidationError("Token size exceeds 2048 bytes when compressed")
        return compressed
