import json
import re
from typing import Dict, List, Optional
import jsonschema
import os

class PronunciationRegistry:
    def __init__(self, schema_path: str = "tools/pronunciation_metadata/schema.json"):
        if not os.path.exists(schema_path):
            schema_path = os.path.join(os.path.dirname(__file__), "schema.json")
        with open(schema_path, "r") as f:
            self.schema = json.load(f)
        self.records: Dict[str, dict] = {}
        # In a real scenario, this would load from a canonical provenance ledger.
        self.provenance_registry = {
            "prov1": "eng",
            "prov2": "fra",
            "prov3": "zho"
        }

    def _validate_ipa(self, ipa: str) -> bool:
        if not ipa:
            return True
        # Reject simple orthography passing as IPA.
        # This is a basic heuristic: true IPA often has non-ASCII phonetic symbols
        # or specific formatting. If it's pure a-z without any IPA diacritics or
        # common IPA vowels/consonants, it's likely just the word spelled out.
        # Let's enforce that IPA cannot just be standard alphabetical letters.
        if re.fullmatch(r'[a-zA-Z]+', ipa):
            # There are English letters that are also IPA, but an entire word
            # made only of a-z with no typical IPA marks (like ˈ, ˌ, ː) is suspicious.
            return False

        # Optional: ensure characters are within expected Unicode IPA ranges
        # For simplicity, we just check it isn't pure basic Latin letters
        return True

    def add_record(self, record_json: str) -> None:
        if len(record_json.encode('utf-8')) > 4096:
            raise ValueError("Record exceeds maximum bounded input size of 4096 bytes")

        try:
            record = json.loads(record_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed JSON: {e}")

        try:
            jsonschema.validate(instance=record, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            raise ValueError(f"Schema validation error: {e}")

        # Validate provenance
        prov_id = record["provenance_id"]
        lang = record["language"]
        if prov_id in self.provenance_registry and self.provenance_registry[prov_id] != lang:
            raise ValueError(f"Wrong language for provenance {prov_id}. Expected {self.provenance_registry[prov_id]}, got {lang}")
        elif prov_id not in self.provenance_registry:
            raise ValueError(f"Unverified provenance source: {prov_id}")

        if "ipa" in record and not self._validate_ipa(record["ipa"]):
            raise ValueError("Invalid IPA symbols detected. May be auto-generated from orthography.")

        # Bind to ID for deterministic sorting and storage. Use lexical_entry_id as primary key
        key = record["lexical_entry_id"]
        self.records[key] = record

    def incremental_update(self, record_json: str) -> None:
        self.add_record(record_json)

    def compile_registry(self) -> List[dict]:
        # Deterministic registry compilation by sorting keys
        return [self.records[k] for k in sorted(self.records.keys())]
