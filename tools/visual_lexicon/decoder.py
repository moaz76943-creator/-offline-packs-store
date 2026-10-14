import json
import zlib
from pathlib import Path
from tools.visual_lexicon.validator import VisualTokenValidator

class VisualTokenDecoder:
    def __init__(self):
        self.validator = VisualTokenValidator()

    def decode(self, file_path):
        # 1. Read .vct file
        with open(file_path, 'rb') as f:
            compressed_payload = f.read()

        # 2. Decompress using zlib
        try:
            compact_json = zlib.decompress(compressed_payload).decode('utf-8')
        except zlib.error as e:
            raise ValueError(f"Failed to decompress token: {e}")

        # 3. Parse JSON
        try:
            token_record = json.loads(compact_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON: {e}")

        # 4. Validate
        self.validator.validate(token_record)

        return token_record
