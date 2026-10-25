import re
import sys
import os

# Ensure the repository root is in the path to allow absolute imports
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from legal.ledger.admission import LICENSES, OBLIGATIONS

LEDGER_SCHEMA = {
    'type': 'object',
    'required': ['source_id', 'url', 'author', 'version', 'license', 'modification_status'],
    'properties': {
        'source_id': {'type': 'string'},
        'url': {'type': 'string', 'pattern': '^https?://'},
        'author': {'type': 'string'},
        'version': {'type': 'string'},
        'license': {
            'type': 'object',
            'required': ['id', 'evidence_url', 'evidence_hash'],
            'properties': {
                'id': {'type': 'string'},
                'evidence_url': {'type': 'string', 'pattern': '^https?://'},
                'evidence_hash': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
            }
        },
        'modification_status': {'type': 'string'}
    }
}

class LicensingLedger:
    def __init__(self):
        pass

    def validate_schema(self, record):
        if not isinstance(record, dict):
            return False, "Record must be an object"

        for req in LEDGER_SCHEMA['required']:
            if req not in record:
                return False, f"Missing required field: {req}"
            if not record[req]:
                if req not in ['modification_status']:
                    return False, f"Empty required field: {req}"

        if 'license' in record:
            lic = record['license']
            if not isinstance(lic, dict):
                return False, "License must be an object"
            for req in LEDGER_SCHEMA['properties']['license']['required']:
                if req not in lic:
                    return False, f"Missing required license field: {req}"
                if not lic[req]:
                    return False, f"Empty required license field: {req}"
            if not re.match(LEDGER_SCHEMA['properties']['license']['properties']['evidence_hash']['pattern'], lic.get('evidence_hash', '')):
                return False, "Invalid evidence_hash"
            if not re.match(LEDGER_SCHEMA['properties']['license']['properties']['evidence_url']['pattern'], lic.get('evidence_url', '')):
                return False, "Invalid evidence_url"

        if not re.match(LEDGER_SCHEMA['properties']['url']['pattern'], record.get('url', '')):
            return False, "Invalid url"

        return True, "Valid"

    def evaluate_sources(self, sources):
        if not sources:
            return 'reviewRequired', ['No sources provided']

        issues = []
        status = 'verified'

        copyleft_licenses_present = set()

        for idx, source in enumerate(sources):
            is_valid, msg = self.validate_schema(source)
            if not is_valid:
                issues.append(f"Source {idx}: {msg}")
                status = 'blocked'
                continue

            lic = source.get('license', {})
            lic_id = lic.get('id')

            if not lic_id:
                issues.append(f"Source {source.get('source_id')}: Missing license id")
                status = 'blocked'
                continue

            if lic_id not in LICENSES:
                issues.append(f"Source {source.get('source_id')}: Unknown license {lic_id}")
                if status != 'blocked':
                    status = 'reviewRequired'
                continue

            if lic_id in OBLIGATIONS:
                copyleft_licenses_present.add(lic_id)
                # Check for fulfilled obligations if provided
                compliance = source.get('compliance', {})
                for req in OBLIGATIONS[lic_id]:
                    if compliance.get(req) is not True:
                        issues.append(f"Source {source.get('source_id')}: Incomplete obligation {req} for {lic_id}")
                        status = 'blocked'

            if lic_id == 'PUBLIC-DOMAIN':
                proof = lic.get('public_domain_proof')
                if not proof:
                    issues.append(f"Source {source.get('source_id')}: Missing public domain proof")
                    status = 'blocked'

            if not source.get('author'):
                issues.append(f"Source {source.get('source_id')}: Missing author")
                status = 'blocked'

        if len(copyleft_licenses_present) > 1:
            issues.append(f"Invalid copyleft mixture: {', '.join(sorted(copyleft_licenses_present))}")
            status = 'blocked'

        if not sources:
            return status, issues

        # If any source is missing a license explicitly, we do not infer public domain
        for source in sources:
            if not source.get('license') or not source['license'].get('id'):
                issues.append("Cannot infer Public Domain from a missing license")
                status = 'blocked'

        return status, issues
