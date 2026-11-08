import json
import os
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.json"

class LicensingValidator:
    def __init__(self):
        try:
            import jsonschema
            self.jsonschema = jsonschema
        except ImportError:
            self.jsonschema = None

        with open(SCHEMA_PATH, 'r') as f:
            self.schema = json.load(f)

    def validate_schema(self, record):
        if self.jsonschema:
            try:
                self.jsonschema.validate(instance=record, schema=self.schema)
                return True
            except self.jsonschema.exceptions.ValidationError:
                return False
        else:
            required = self.schema.get("required", [])
            for req in required:
                if req not in record:
                    return False
            if "license" in record:
                lic_reqs = self.schema["properties"]["license"].get("required", [])
                for req in lic_reqs:
                    if req not in record["license"]:
                        return False
            return True

    def evaluate_record(self, record, previous_record=None):
        if not self.validate_schema(record):
            return "blocked"

        if not record.get("author") or not record.get("source_id"):
            return "blocked"

        license_data = record.get("license", {})
        declaration = license_data.get("declaration", "")
        evidence = license_data.get("evidence", {})

        if not declaration:
            return "blocked"

        if declaration == "CC-BY-SA-4.0":
            if not evidence.get("attribution") or not evidence.get("share_alike"):
                return "blocked"

        if declaration == "GFDL-1.3-only":
            if not evidence.get("gfdl_history"):
                return "blocked"

        if declaration == "PUBLIC-DOMAIN" or declaration == "Public Domain":
            if not evidence.get("public_domain"):
                return "reviewRequired" # Never infer Public Domain

        if previous_record:
            if previous_record.get("version") != record.get("version") or previous_record.get("artifact_hash") != record.get("artifact_hash"):
                return "reviewRequired"

        return record.get("status", "verified")

    def evaluate_release(self, records):
        has_gfdl = False
        has_cc_by_sa = False

        for record in records:
            status = self.evaluate_record(record)
            if status == "blocked":
                return "blocked"
            if status == "reviewRequired":
                return "reviewRequired"

            decl = record.get("license", {}).get("declaration", "")
            if decl == "GFDL-1.3-only":
                has_gfdl = True
            elif decl == "CC-BY-SA-4.0":
                has_cc_by_sa = True

        if has_gfdl and has_cc_by_sa:
            return "reviewRequired"

        return "verified"
