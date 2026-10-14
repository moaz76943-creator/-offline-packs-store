import json
import jsonschema
from pathlib import Path

class VisualLexiconAPI:
    def __init__(self, manifest_path="media/semantic_icons/manifest.json"):
        self.manifest_path = Path(manifest_path)
        self.manifest_schema_path = Path(__file__).resolve().parent / 'manifest.schema.json'

        with open(self.manifest_schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

        self.manifest = self._load_manifest()

    def _load_manifest(self):
        if not self.manifest_path.exists():
            return {}
        with open(self.manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
            jsonschema.validate(instance=manifest, schema=self.schema)
            return manifest

    def _save_manifest(self):
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        jsonschema.validate(instance=self.manifest, schema=self.schema)
        # Output incrementally with deterministic sorting
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self.manifest, f, sort_keys=True, indent=2)
            f.write('\n')

    def register_token(self, concept_id, token_hash):
        if not isinstance(token_hash, str) or len(token_hash) != 64:
            raise ValueError(f"Invalid token hash: {token_hash}")

        if concept_id in self.manifest and self.manifest[concept_id] != token_hash:
            raise ValueError(f"Concept identity collision: concept '{concept_id}' is already mapped to a different hash ({self.manifest[concept_id]}). Updating to {token_hash} requires explicit override.")

        self.manifest[concept_id] = token_hash
        self._save_manifest()

    def get_token_hash(self, concept_id):
        return self.manifest.get(concept_id)
