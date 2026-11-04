import json
import os

class LicensingLedgerValidator:
    def __init__(self, schema_path=None):
        if schema_path is None:
            schema_path = os.path.join(os.path.dirname(__file__), 'schema.json')
        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

    def validate(self, record):
        # 1. Enforce required fields
        for field in self.schema.get('required', []):
            if field not in record or not record[field]:
                return 'BLOCKED'

        # 2. Extract licenses to check
        declared = record.get('declared_license', '')
        evidence = record.get('verified_evidence', '')

        # 3. Block inferred Public Domain without verified evidence
        if 'public domain' in declared.lower() or 'cc0' in declared.lower():
            if not evidence:
                return 'BLOCKED'

        # 4. Enforce GFDL provenance (require version)
        if 'gfdl' in declared.lower():
            if not record.get('version'):
                return 'BLOCKED'

        # 5. Enforce CC BY-SA obligations (require url or verified_evidence)
        if 'cc by-sa' in declared.lower() or 'cc-by-sa' in declared.lower():
            if not record.get('url') and not evidence:
                return 'BLOCKED'

        # 6. Check uncertain copyleft combinations (e.g. mixing CC BY-SA and GFDL)
        mixed_sources = record.get('mixed_sources', [])
        mixed_licenses = [s.get('license', '').lower() for s in mixed_sources]

        # Check combinations in mixed_sources and declared_license
        all_licenses = [declared.lower()] + mixed_licenses
        has_cc_bysa = any('cc by-sa' in l or 'cc-by-sa' in l for l in all_licenses)
        has_gfdl = any('gfdl' in l for l in all_licenses)

        if has_cc_bysa and has_gfdl:
            return 'REVIEW_REQUIRED'

        # 7. Check if license requires review due to unknown or generic declared license without evidence
        # E.g. copyleft licenses that are ambiguous
        # If no verified evidence is present, and we have an ambiguous license declaration
        if 'copyleft' in declared.lower() and not evidence:
            return 'REVIEW_REQUIRED'

        # Return VERIFIED if all checks pass
        return 'VERIFIED'
