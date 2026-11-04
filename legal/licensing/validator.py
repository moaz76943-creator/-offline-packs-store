

class LicensingValidator:
    def __init__(self):
        self.KNOWN_LICENSES = {
            'CC BY-SA 3.0',
            'CC BY-SA 4.0',
            'GFDL-1.3',
            'CC BY 4.0',
            'CC0-1.0',
            'Public Domain',
            'MIT',
            'Apache-2.0'
        }

    def validate_record(self, record):
        required_fields = ['source_id', 'url', 'author', 'version', 'license', 'modification_status']
        for field in required_fields:
            if not record.get(field):
                return 'blocked'

            # Additional safety for missing fields
            if record.get(field) == '___MISSING_AUTHOR___':
                return 'blocked'

        declared_license = record['license']
        if declared_license not in self.KNOWN_LICENSES:
            return 'blocked'

        # Never infer Public Domain from a missing license
        # The schema and required field checks already catch missing licenses

        # Check verified evidence
        evidence = record.get('verified_evidence')
        if not evidence:
            return 'reviewRequired'

        if not evidence.get('license_text_found') or not evidence.get('attribution_found'):
            return 'reviewRequired'

        return 'verified'

    def evaluate_release(self, records):
        if not records:
            return 'blocked'

        statuses = set()
        licenses = set()

        for record in records:
            status = self.validate_record(record)
            statuses.add(status)
            licenses.add(record.get('license'))

        if 'blocked' in statuses:
            return 'blocked'

        # Check for mixed incompatible licenses
        has_cc_by_sa = any('CC BY-SA' in lic for lic in licenses if lic)
        has_gfdl = any('GFDL' in lic for lic in licenses if lic)

        if has_cc_by_sa and has_gfdl:
            return 'reviewRequired'

        if 'reviewRequired' in statuses:
            return 'reviewRequired'

        return 'verified'
