"""Pure Python validator for the Open Lexical Source Licensing Ledger."""
import json
import re

class LicensingValidator:
    """Validates records against the licensing ledger schema."""

    REQUIRED_FIELDS = ['source_id', 'url', 'author', 'version', 'license', 'modification_status']
    KNOWN_LICENSES = {'CC-BY-SA-4.0', 'GFDL-1.3-only', 'CC0-1.0', 'PUBLIC-DOMAIN', 'CC-BY-2.0-FR'}

    def validate_record(self, record: dict):
        """Raises ValueError if a record is missing required fields or has invalid types."""
        if not isinstance(record, dict):
            raise ValueError("Record must be a dictionary")

        for field in self.REQUIRED_FIELDS:
            if field not in record:
                raise ValueError(f"Missing required field: {field}")
            # we will validate specific fields below rather than a generic falsy check

        # Basic validation of field contents
        if not isinstance(record['source_id'], str) or not record['source_id']:
            raise ValueError("source_id must be a non-empty string")
        if not isinstance(record['author'], str) or not record['author']:
            raise ValueError("author must be a non-empty string")

        license_obj = record['license']
        if not isinstance(license_obj, dict):
            raise ValueError("license must be an object")

        if 'id' not in license_obj or not license_obj['id']:
            raise ValueError("license.id must be a non-empty string. Public Domain cannot be inferred from a missing license.")

    def evaluate_record(self, record: dict) -> str:
        """
        Evaluates a record for redistribution eligibility.
        Returns 'verified', 'blocked', or 'reviewRequired'.
        """
        try:
            self.validate_record(record)
        except ValueError:
            return 'blocked'

        license_id = record['license'].get('id')

        if not record.get('verified_evidence'):
            # It requires verified evidence for some things, but maybe just evidence.
            # If not verified, and it's a copyleft license, it might need review or be blocked.
            # We'll fail closed if verified_evidence is missing or False, unless it's a very simple case,
            # but even then the objective says "blocking distribution when required evidence is missing"
            # However, distinguish license declarations from verified evidence.
            # Let's say if it lacks verified evidence, it's blocked, unless we flag it as reviewRequired.
            # "Record redistribution eligibility as verified, blocked or reviewRequired."
            if license_id not in self.KNOWN_LICENSES:
                return 'reviewRequired'

            # If evidence is missing for CC-BY-SA or GFDL, it's blocked or reviewRequired
            if not record['license'].get('evidence_url') and not record['license'].get('evidence_sha256'):
                return 'blocked'

        if license_id not in self.KNOWN_LICENSES:
            return 'reviewRequired'

        # Treat legally uncertain combinations as reviewRequired (e.g., dual license string in 'id'?)
        if isinstance(license_id, list) or ',' in license_id or ' and ' in license_id.lower():
            return 'reviewRequired'

        # Verified if all good
        if record.get('verified_evidence', False):
            return 'verified'

        # If it has evidence but verified_evidence flag isn't true yet, review it
        return 'reviewRequired'

    def evaluate_release(self, records: list) -> str:
        """
        Evaluates a release (list of records).
        Aggregates statuses and flags mixed GFDL and CC BY-SA records across a release for review.
        """
        if not isinstance(records, list):
            raise ValueError("records must be a list")

        has_gfdl = False
        has_cc_by_sa = False

        overall_status = 'verified'

        for record in records:
            status = self.evaluate_record(record)
            if status == 'blocked':
                return 'blocked'
            if status == 'reviewRequired':
                overall_status = 'reviewRequired'

            try:
                self.validate_record(record)
                license_id = record['license']['id']
                if 'GFDL' in license_id:
                    has_gfdl = True
                if 'CC-BY-SA' in license_id:
                    has_cc_by_sa = True
            except ValueError:
                pass

        if has_gfdl and has_cc_by_sa:
            return 'reviewRequired'

        return overall_status
