import hashlib
import json
from .token import CompactVectorToken, TokenValidationError

class VectorPackCompiler:
    def __init__(self):
        self.geometry_registry = {}  # hash(geometry) -> geometry_id
        self.next_geometry_id = 0
        self.concepts = {}
        self.manifest = {
            "pack_version": 1,
            "decoder_compatibility": "WordBit-Vector-v1",
            "concepts": {},
            "geometries": {}
        }
        self.previous_pack = None

    def load_previous_pack(self, previous_pack_dict):
        """Loads a previous pack to enable incremental deduplication."""
        self.previous_pack = previous_pack_dict
        if "geometries" in previous_pack_dict:
            self.manifest["geometries"] = previous_pack_dict["geometries"].copy()
            # update next_geometry_id
            if self.manifest["geometries"]:
                max_id = max(int(k) for k in self.manifest["geometries"].keys())
                self.next_geometry_id = max_id + 1
            for gid, geom in self.manifest["geometries"].items():
                geom_hash = self._hash_geometry(geom)
                self.geometry_registry[geom_hash] = str(gid)
        if "concepts" in previous_pack_dict:
            self.manifest["concepts"] = previous_pack_dict["concepts"].copy()

    def _hash_geometry(self, paths: list) -> str:
        data = json.dumps(paths, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(data).hexdigest()

    def add_token(self, token: CompactVectorToken):
        geom_hash = self._hash_geometry(token.geometry_paths)
        if geom_hash not in self.geometry_registry:
            gid = str(self.next_geometry_id)
            self.next_geometry_id += 1
            self.geometry_registry[geom_hash] = gid
            self.manifest["geometries"][gid] = token.geometry_paths
        else:
            gid = self.geometry_registry[geom_hash]

        # Check if concept already exists and has changed (incremental delta)
        concept_entry = {
            "version": token.version,
            "source_hash": token.source_hash,
            "license": token.license,
            "geometry_id": gid
        }

        # We process the token
        self.manifest["concepts"][token.concept_id] = concept_entry

    def compile(self) -> bytes:
        # Deterministic JSON dump
        return json.dumps(self.manifest, separators=(',', ':'), sort_keys=True).encode('utf-8')


    def build_pack(self, tokens_data: list):
        """
        tokens_data: list of bytes representing the compact vector tokens (.vct contents)
        """
        for data in tokens_data:
            try:
                token = CompactVectorToken.from_bytes(data)

                # Deduplicate: if we already have this concept with same source_hash, we can reuse
                if self.previous_pack and token.concept_id in self.previous_pack.get("concepts", {}):
                    prev_concept = self.previous_pack["concepts"][token.concept_id]
                    if prev_concept["source_hash"] == token.source_hash and prev_concept["version"] == token.version:
                        # Reuse unchanged token
                        self.manifest["concepts"][token.concept_id] = prev_concept
                        continue

                self.add_token(token)
            except TokenValidationError as e:
                # Reject malformed or unlicensed tokens
                # We could log this or handle it depending on the exact requirements
                raise
