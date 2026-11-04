import json
import os
import jsonschema

class LicensingLedgerValidator:
    def __init__(self, schema_path=None):
        if schema_path is None:
            schema_path = os.path.join(os.path.dirname(__file__), 'schema.json')
        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

    def validate_record(self, record):
        try:
            jsonschema.validate(instance=record, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            return {"status": "blocked", "reason": f"Schema validation failed: {e.message}"}

        license_data = record.get('license', {})
        license_id = license_data.get('id')

        # Missing license block
        if not license_id:
            return {"status": "blocked", "reason": "Missing license"}

        # Determine eligibility based on license
        if license_id == "UNVERIFIED":
            return {"status": "reviewRequired", "reason": "License is unverified"}

        if license_id == "PUBLIC-DOMAIN":
            proof = license_data.get('public_domain_proof')
            if not proof or not proof.get('jurisdiction') or not proof.get('legal_basis') or not proof.get('work_date'):
                return {"status": "reviewRequired", "reason": "Public domain requires explicit proof (jurisdiction, legal_basis, work_date)"}

        if license_id == "CC-BY-SA-4.0":
            if not license_data.get('evidence_url') and not license_data.get('evidence_path'):
                 return {"status": "reviewRequired", "reason": "CC-BY-SA-4.0 requires explicit evidence (url or path)"}

        if license_id == "GFDL-1.3-only":
            if not license_data.get('evidence_url') and not license_data.get('evidence_path'):
                 return {"status": "reviewRequired", "reason": "GFDL-1.3-only requires explicit evidence (url or path)"}
            if not license_data.get('gfdl_copy_path'):
                return {"status": "reviewRequired", "reason": "GFDL-1.3-only requires gfdl_copy_path"}

        # Modification rules
        if record.get('modification_status') == "modified":
            if license_id not in ["CC-BY-SA-4.0", "GFDL-1.3-only", "CC0-1.0", "PUBLIC-DOMAIN", "OFL-1.1", "Apache-2.0", "MIT"]:
                 return {"status": "reviewRequired", "reason": f"Modifications for license {license_id} require review"}

        return {"status": "verified", "reason": "Validation successful"}

    def evaluate_ledger(self, ledger_records):
        results = []
        for record in ledger_records:
            results.append(self.validate_record(record))
        return results
