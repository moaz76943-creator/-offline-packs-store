import json
import zlib
import hashlib
from pathlib import Path
from tools.visual_lexicon.validator import VisualTokenValidator

class VisualTokenEncoder:
    def __init__(self, output_dir="media/semantic_icons"):
        self.validator = VisualTokenValidator()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def encode(self, token_record):
        # 1. Validate structure and complexity
        self.validator.validate(token_record)

        # 2. Serialize to compact JSON
        compact_json = json.dumps(token_record, separators=(',', ':'), sort_keys=True).encode('utf-8')

        # 3. Zlib compress
        compressed_payload = zlib.compress(compact_json)

        # 4. Check size limit
        if len(compressed_payload) > 2048:
            raise ValueError(f"Compressed token size {len(compressed_payload)} exceeds limit of 2048 bytes")

        # 5. Generate deterministic SHA-256 hash from canonical JSON, not compressed bytes
        hash_digest = hashlib.sha256(compact_json).hexdigest()

        # 6. Save .vct file
        output_path = self.output_dir / f"{hash_digest}.vct"
        with open(output_path, 'wb') as f:
            f.write(compressed_payload)

        return hash_digest, output_path
