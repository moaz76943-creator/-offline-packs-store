import os
import json
from pathlib import Path
from tools.visual_lexicon.core import encode_token, decode_token
from tools.visual_lexicon.schema import validate_manifest

class ConceptStore:
    def __init__(self, root_dir: str = 'media/semantic_icons'):
        self.root_dir = Path(root_dir)
        self.manifest_path = self.root_dir / 'manifest.json'

        if not self.root_dir.exists():
            self.root_dir.mkdir(parents=True, exist_ok=True)

        self._manifest_cache = None

    def _load_manifest(self) -> dict:
        if self._manifest_cache is not None:
            return self._manifest_cache

        if not self.manifest_path.exists():
            return {}

        with open(self.manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self._manifest_cache = data
            return data

    def _save_manifest(self, data: dict):
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, sort_keys=True)
        self._manifest_cache = data

    def add_token(self, concept_id: str, token_data: dict, manifest_data: dict):
        """
        Checks the manifest and geometries, encodes the token, and saves it.
        Validates real author, source and license evidence.
        """
        # Ensure semantic consistency
        if token_data.get('concept_id') != concept_id:
            raise ValueError(f"concept_id mismatch: token has {token_data.get('concept_id')} but added under {concept_id}")
        if manifest_data.get('concept_id') != concept_id:
            raise ValueError(f"concept_id mismatch: manifest has {manifest_data.get('concept_id')} but added under {concept_id}")

        validate_manifest(manifest_data)

        compressed, token_hash = encode_token(token_data)

        # Save token
        token_filename = f"{concept_id}.vct"
        token_path = self.root_dir / token_filename
        with open(token_path, 'wb') as f:
            f.write(compressed)

        # Update manifest
        manifest = self._load_manifest()

        # We append deterministic state to track updates
        manifest_data['hash'] = token_hash
        manifest_data['file'] = token_filename

        manifest[concept_id] = dict(manifest_data)
        self._save_manifest(manifest)

    def get_token(self, concept_id: str) -> dict:
        """
        Retrieves a token by concept_id and decodes it.
        """
        manifest = self._load_manifest()
        if concept_id not in manifest:
            raise KeyError(f"concept_id {concept_id} not found in manifest")

        token_filename = manifest[concept_id]['file']
        token_path = self.root_dir / token_filename

        if not token_path.exists():
            raise FileNotFoundError(f"Token file {token_path} is missing")

        with open(token_path, 'rb') as f:
            compressed = f.read()

        return decode_token(compressed)
