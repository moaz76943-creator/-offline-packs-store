
LICENSES = {'CC-BY-SA-4.0', 'GFDL-1.3-only', 'CC0-1.0', 'PUBLIC-DOMAIN'}

OBLIGATIONS = {
    'CC-BY-SA-4.0': ('attribution', 'license_link', 'changes_disclosed',
                     'sharealike', 'no_additional_restrictions'),
    'GFDL-1.3-only': ('license_copy', 'copyright_notices', 'history',
                      'invariant_sections_checked', 'cover_texts_checked',
                      'transparent_copy_checked'),
}


def text(val):
    return isinstance(val, str) and bool(val.strip())

class LedgerAPI:
    def __init__(self, records_list=None):
        self.records = {}
        if records_list:
            for r in records_list:
                self.add_record(r)

    def add_record(self, record):
        if text(record.get('source_id')):
            self.records[record['source_id']] = record

    def validate_record(self, record, actual_hash=None):
        out = []
        if not text(record.get('source_id')):
            out.append('BLOCKED: missing source identity')
        if not text(record.get('author')):
            out.append('BLOCKED: missing author')
        if not text(record.get('url')):
            out.append('BLOCKED: missing url')
        if not text(record.get('version')):
            out.append('BLOCKED: missing version')

        expected_hash = record.get('hash')
        if actual_hash and expected_hash and actual_hash != expected_hash:
            out.append('BLOCKED: hash mismatch / changed source version')

        license_info = record.get('license')
        if not license_info:
            out.append('BLOCKED: missing license')
            # Never infer Public Domain status from a missing license.
            return sorted(set(out))

        declared = license_info.get('declared_license')
        if not declared:
            out.append('BLOCKED: missing declared license')
            return sorted(set(out))

        if declared not in LICENSES:
            out.append(f'BLOCKED: unsupported license {declared}')

        evidence = license_info.get('evidence')
        if not isinstance(evidence, dict) or not evidence.get('verified'):
            out.append('BLOCKED: missing or unverified license evidence')

        if declared in OBLIGATIONS and isinstance(evidence, dict):
            obligations_met = evidence.get('obligations_met', {})
            for req in OBLIGATIONS[declared]:
                if not obligations_met.get(req, False):
                    out.append(f'BLOCKED: incomplete obligation {req} for {declared}')

        return sorted(set(out))

    def evaluate_provenance(self, source_ids):
        """
        Evaluate a set of sources to determine mixed-source redistribution eligibility.
        Preserves mixed-source provenance without collapsing licenses.
        Returns: 'verified', 'blocked', or 'reviewRequired'
        """
        if not source_ids:
            return 'blocked'

        licenses_found = set()
        for sid in source_ids:
            if sid not in self.records:
                return 'blocked'

            record = self.records[sid]
            errors = self.validate_record(record)
            if errors:
                return 'blocked'

            licenses_found.add(record['license']['declared_license'])

        copyleft_found = {lic for lic in licenses_found if lic in OBLIGATIONS}

        # Treat legally uncertain combinations as reviewRequired.
        # Examples of legally uncertain combinations: multiple copyleft licenses
        if len(copyleft_found) > 1:
            return 'reviewRequired'

        # If there is a copyleft license mixed with PUBLIC-DOMAIN or CC0, it might be fine
        # but to be safe and rigorous based on ledger rules (GFDL and CC-BY-SA cannot be assumed interchangeable)
        # We explicitly handled the len > 1 case above.
        # But wait, what if we have CC-BY-SA and we are outputting as something else?
        # The prompt says: "Preserve mixed-source provenance without collapsing licenses."
        # And "Treat legally uncertain combinations as reviewRequired."
        # For now, returning verified for single copyleft or pure permissive is correct.

        return 'verified'
