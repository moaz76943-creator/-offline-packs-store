import json
import jsonschema
import unicodedata
import os
from pathlib import Path

class PronunciationRegistry:
    def __init__(self, schema_path=None):
        if schema_path is None:
            schema_path = Path(__file__).parent / "schema.json"
        else:
            schema_path = Path(schema_path)

        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

        self.records = {}

    def _validate_ipa(self, ipa_string):
        """Validate that all characters in the IPA string are valid Unicode and not control characters."""
        if not ipa_string:
            return
        # Reject basic control chars or unassigned
        for char in ipa_string:
            category = unicodedata.category(char)
            if category.startswith("C"):
                raise ValueError(f"Invalid character in IPA string: {repr(char)}")

    def _validate_input_bounds(self, record):
        """Enforce strict bounded serialization and input size limits."""
        serialized = json.dumps(record, ensure_ascii=False)
        if len(serialized.encode("utf-8")) > 4096:
            raise ValueError("Record exceeds maximum bounded input size of 4096 bytes")

    def add_record(self, record, catalog_validator=None):
        """Validates and adds a pronunciation record to the registry."""
        # 1. Bounded size validation
        self._validate_input_bounds(record)

        # 2. Schema validation
        try:
            jsonschema.validate(instance=record, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            raise ValueError(f"Schema validation failed: {e.message}")

        # 3. Unicode IPA Validation
        if "ipa" in record:
            self._validate_ipa(record["ipa"])

        # 4. Do not fabricate pronunciations or claim offline voice blindly
        if "ipa" not in record and "phonetic_transliteration" not in record and "variants" not in record and "phonetic_notes" not in record:
             raise ValueError("Pronunciation record lacks any actual pronunciation data (ipa, phonetic_transliteration, variants, phonetic_notes)")

        # 5. Require a language
        if "language" not in record:
             raise ValueError("Record missing required 'language' field")

        # Optional external catalog validation of language and source (mock hook for the broader system)
        if catalog_validator:
            catalog_validator(record)

        # 6. Check for valid unknown offline voice tracking
        if record.get("offline_voice_availability") not in ["supported", "unsupported", "unknown"]:
            raise ValueError("Invalid offline_voice_availability")

        # Key by record ID
        rid = record["id"]

        # Incremental check: only add/update if it's new or the source_version has changed
        if rid in self.records:
            existing = self.records[rid]
            # Simple provenance-based incremental update logic
            if existing.get("provenance_id") != record.get("provenance_id") or existing.get("source_version") != record.get("source_version"):
                self.records[rid] = record
            else:
                # Same version/provenance, skip update
                pass
        else:
            self.records[rid] = record

    def compile(self):
        """Deterministically compile the registry to a sorted JSON string."""
        # Sort by record ID for deterministic output
        sorted_records = []
        for key in sorted(self.records.keys()):
            # Create a new dict with keys sorted deterministically
            record = self.records[key]
            sorted_record = {k: record[k] for k in sorted(record.keys())}
            sorted_records.append(sorted_record)

        return json.dumps(sorted_records, ensure_ascii=False, indent=2, separators=(',', ': '))

    def incremental_update(self, stream_of_records, catalog_validator=None):
        """Process a stream of records for incremental updates."""
        updated = 0
        added = 0
        skipped = 0

        for record in stream_of_records:
            rid = record.get("id")
            if not rid:
                raise ValueError("Record missing required 'id' field")

            is_new = rid not in self.records
            was_updated = False

            if not is_new:
                existing = self.records[rid]
                if existing.get("provenance_id") != record.get("provenance_id") or existing.get("source_version") != record.get("source_version"):
                    was_updated = True

            self.add_record(record, catalog_validator)

            if is_new:
                added += 1
            elif was_updated:
                updated += 1
            else:
                skipped += 1

        return {"added": added, "updated": updated, "skipped": skipped}
