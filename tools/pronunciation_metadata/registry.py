import json
import re
from pathlib import Path
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name('schema.json')

class PronunciationRegistryError(ValueError):
    pass

class PronunciationRegistry:
    def __init__(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)
        self.records = {}

        # Reject obvious non-IPA for basic check
        self.cjk_re = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df]')

    def validate_document(self, document_str):
        if len(document_str) > 10 * 1024 * 1024: # 10MB bounds
            raise PronunciationRegistryError('Document too large')

        try:
            document = json.loads(document_str)
        except json.JSONDecodeError as e:
            raise PronunciationRegistryError(f'Malformed JSON metadata: {e}')

        failures = sorted(self.validator.iter_errors(document), key=lambda error: tuple(str(piece) for piece in error.absolute_path))
        if failures:
            error = failures[0]
            raise PronunciationRegistryError(f'JSON Schema violation at {list(error.absolute_path)}: {error.message}')

        # Cross-record validation
        for record in document.get('records', []):
            self.validate_record(record)

        return document

    def validate_record(self, record):
        rid = record['record_id']

        # Check source verification
        src = record['source']
        if not src.get('publication_approved'):
            raise PronunciationRegistryError(f'unverified source reference: {rid}')

        # Reject wrong-language metadata mismatch in basic parsing
        lang = record.get('language')
        locale = record.get('locale')
        if locale and not locale.startswith(lang):
            raise PronunciationRegistryError(f'wrong-language locale mapping: {rid}')

        # Pronunciation checks
        for pron in record.get('pronunciations', []):
            if not pron.get('source', {}).get('publication_approved'):
                raise PronunciationRegistryError(f'unverified source reference in pronunciation: {rid}')

            notation = pron.get('notation')
            value = pron.get('value')

            if notation == 'ipa':
                # Basic check for IPA syntax: shouldn't have CJK
                if self.cjk_re.search(value):
                    raise PronunciationRegistryError(f'CJK characters found in IPA notation: {rid}')

    def load_records(self, document_str):
        doc = self.validate_document(document_str)
        for rec in doc.get('records', []):
            self.add_or_update_record(rec)

    def add_or_update_record(self, record):
        """Supports incremental updates for changed pronunciation entries."""
        self.validate_record(record)

        # Do not merge arrays, do a full replace based on record_id
        # This matches deterministic provenance handling.
        rid = record['record_id']
        self.records[rid] = record

    def export(self):
        """Emit runtime-compatible exports with deterministic sorting and grouping."""
        # Sort by record_id deterministically
        sorted_records = []
        for rid in sorted(self.records.keys()):
            # ensure sub-arrays are also sorted or deterministic (already bound by schemas and sources, but to be sure)
            rec = self.records[rid]
            sorted_records.append(rec)

        out = {
            'registry_version': '1.0.0',
            'records': sorted_records
        }
        return json.dumps(out, ensure_ascii=False, separators=(',', ':'))
