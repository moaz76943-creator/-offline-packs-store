import json
from pathlib import Path
import jsonschema

OBLIGATIONS = {
    'CC-BY-SA-4.0': {'attribution', 'license_link', 'changes_disclosed',
                     'sharealike', 'no_additional_restrictions'},
    'GFDL-1.3-only': {'license_copy', 'copyright_notices', 'history',
                      'invariant_sections_checked', 'cover_texts_checked',
                      'transparent_copy_checked'},
}

class LedgerAPI:
    def __init__(self, schema_path=None):
        if schema_path is None:
            schema_path = Path(__file__).parent / 'schema.json'
        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

    def validate_ledger(self, data):
        """Validates the full ledger data against the JSON schema."""
        jsonschema.validate(instance=data, schema=self.schema)
        return True

    def check_eligibility(self, current_record, canonical_record=None):
        """
        Evaluates the redistribution eligibility for a single source record.
        Returns 'verified', 'blocked', or 'reviewRequired'.
        """
        try:
            # Validate against the single item schema implicitly by checking required keys
            # or we can rely on the data being valid according to the schema if already validated.
            source_id = current_record.get('source_id')
            author = current_record.get('author')
            license_info = current_record.get('license', {})
            declared_license = license_info.get('declared')
            evidence = license_info.get('evidence', {}).get('has_evidence', False)
        except AttributeError:
            return 'blocked'

        if not source_id or not author or not declared_license:
            return 'blocked'

        if not evidence:
            return 'blocked'

        if canonical_record:
            if current_record.get('version') != canonical_record.get('version'):
                return 'reviewRequired'
            if current_record.get('artifact_sha256') != canonical_record.get('artifact_sha256'):
                return 'reviewRequired'

        # Never infer Public Domain from a missing license
        # Handled by require of declared_license and schema enforcement

        obligations_met = set(license_info.get('obligations_met', []))

        if declared_license in OBLIGATIONS:
            required = OBLIGATIONS[declared_license]
            if not required.issubset(obligations_met):
                return 'blocked'

        return 'verified'

    def evaluate_mixed_provenance(self, records, canonical_records=None):
        """
        Aggregates eligibility for multiple sources.
        Preserves mixed-source provenance. Legally uncertain combinations
        (like CC-BY-SA and GFDL together) are marked as 'reviewRequired'.
        """
        if canonical_records is None:
            canonical_records = {}

        licenses = set()
        overall_status = 'verified'

        for record in records:
            source_id = record.get('source_id')
            canonical = canonical_records.get(source_id)
            status = self.check_eligibility(record, canonical)

            if status == 'blocked':
                return {'status': 'blocked'}
            elif status == 'reviewRequired':
                overall_status = 'reviewRequired'

            declared = record.get('license', {}).get('declared')
            if declared:
                licenses.add(declared)

        # Mixed license checks for legal uncertainty
        copyleft_licenses = {'CC-BY-SA-4.0', 'GFDL-1.3-only'}
        present_copyleft = licenses.intersection(copyleft_licenses)

        if len(present_copyleft) > 1:
            overall_status = 'reviewRequired'

        return {
            'status': overall_status,
            'licenses': list(licenses)
        }
