import json
import os
from pathlib import Path
from typing import Dict, Optional
from .encoder import TokenEncoder
from .decoder import TokenDecoder

class VisualLexiconAPI:
    def __init__(self, media_dir: str = 'media/semantic_icons', manifest_path: str = 'media/semantic_icons/manifest.json'):
        self.media_dir = Path(media_dir)
        self.manifest_path = Path(manifest_path)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self._manifest: Dict[str, str] = self._load_manifest()

    def _load_manifest(self) -> Dict[str, str]:
        if self.manifest_path.exists():
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save_manifest(self) -> None:
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self._manifest, f, sort_keys=True, indent=2)

    def register_token(self, concept_id: str, token: dict) -> str:
        """
        Validates and registers a visual token for a concept.
        Prevents concept identity collisions: raises ValueError if concept_id exists with a different hash.
        Returns the hash of the saved token.
        """
        compressed_bytes, token_hash = TokenEncoder.encode(token)

        # Check concept collision
        if concept_id in self._manifest:
            existing_hash = self._manifest[concept_id]
            if existing_hash != token_hash:
                raise ValueError(
                    f"Concept collision: {concept_id} is already mapped to hash {existing_hash}, "
                    f"cannot map to new hash {token_hash}."
                )
            # Already registered with the exact same hash
            return token_hash

        # Write asset file if it doesn't exist
        asset_path = self.media_dir / f"{token_hash}.vct"
        if not asset_path.exists():
            with open(asset_path, 'wb') as f:
                f.write(compressed_bytes)

        # Update manifest
        self._manifest[concept_id] = token_hash
        self._save_manifest()

        return token_hash

    def get_token(self, concept_id: str) -> Optional[dict]:
        """
        Retrieves a decoded token for a given concept.
        """
        if concept_id not in self._manifest:
            return None

        token_hash = self._manifest[concept_id]
        asset_path = self.media_dir / f"{token_hash}.vct"

        if not asset_path.exists():
            return None

        with open(asset_path, 'rb') as f:
            compressed_bytes = f.read()

        token, _ = TokenDecoder.decode(compressed_bytes)
        return token
