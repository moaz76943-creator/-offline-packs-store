import json
import jsonschema
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.json"

class LedgerAPI:
    def __init__(self):
        with open(SCHEMA_PATH, "r") as f:
            self.schema = json.load(f)

    def validate_record(self, record):
        try:
            jsonschema.validate(instance=record, schema=self.schema)
        except jsonschema.ValidationError:
            return "blocked"

        license_str = record.get("license", "")
        if not license_str:
            return "blocked"

        if "public domain" in license_str.lower():
            if "public_domain_proof" not in record:
                return "blocked"
            return "verified"

        if "cc by-sa" in license_str.lower():
            if not record.get("license_evidence"):
                return "blocked"
            return "verified"

        if "gfdl" in license_str.lower():
            if not record.get("license_evidence"):
                return "blocked"
            return "verified"

        return "reviewRequired"

    def evaluate_mixed_provenance(self, records):
        if not records:
            return "blocked"

        statuses = [self.validate_record(r) for r in records]

        if "blocked" in statuses:
            return "blocked"

        if "reviewRequired" in statuses:
            return "reviewRequired"

        licenses = [r.get("license", "").lower() for r in records]

        has_cc_by_sa = any("cc by-sa" in l for l in licenses)
        has_gfdl = any("gfdl" in l for l in licenses)

        if has_cc_by_sa and has_gfdl:
            return "reviewRequired"

        return "verified"
