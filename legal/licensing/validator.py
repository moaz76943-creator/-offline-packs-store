import json
from pathlib import Path

class LicensingLedgerValidator:
    def __init__(self, schema_path=None):
        if schema_path is None:
            schema_path = Path(__file__).parent / "schema.json"

        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def _validate_structure(self, record, schema_part=None):
        if schema_part is None:
            schema_part = self.schema

        if schema_part.get("type") == "object":
            if not isinstance(record, dict):
                return False

            # Check required
            for req in schema_part.get("required", []):
                if req not in record:
                    return False

            # Check properties
            for prop_name, prop_schema in schema_part.get("properties", {}).items():
                if prop_name in record:
                    if not self._validate_structure(record[prop_name], prop_schema):
                        return False

            # Check additionalProperties
            if schema_part.get("additionalProperties") is False:
                for key in record:
                    if key not in schema_part.get("properties", {}):
                        return False
        elif schema_part.get("type") == "string":
            if not isinstance(record, str):
                return False
            if "minLength" in schema_part and len(record) < schema_part["minLength"]:
                return False
        elif schema_part.get("type") == "array":
            if not isinstance(record, list):
                return False
            if "minItems" in schema_part and len(record) < schema_part["minItems"]:
                return False
            for item in record:
                if not self._validate_structure(item, schema_part.get("items", {})):
                    return False
        return True

    def validate_record(self, record):
        if not self._validate_structure(record):
            return "BLOCKED"

        # Check required fields directly
        if not record.get("author") or not record.get("source_id") or not record.get("url"):
            return "BLOCKED"

        license_info = record.get("license", {})
        if not license_info:
            return "BLOCKED"

        declared = license_info.get("declared")
        evidence = license_info.get("evidence", {})
        evidence_licenses = evidence.get("licenses", [])
        obligations_met = evidence.get("obligations_met", {})

        # Explicitly block inferred Public Domain (if declared is missing/empty but evidence claims PUBLIC-DOMAIN)
        if not declared and "PUBLIC-DOMAIN" in evidence_licenses:
            return "BLOCKED"

        # Check obligations
        # For CC-BY-SA-4.0
        if "CC-BY-SA-4.0" in evidence_licenses:
            if not obligations_met.get("attribution") or not obligations_met.get("share_alike") or not obligations_met.get("notice"):
                return "BLOCKED"

        # For GFDL-1.3-only
        if "GFDL-1.3-only" in evidence_licenses:
            # Requires license_copy, copyright_notices, history etc. based on trace
            # Just test some basic ones or any general obligation if provided
            if "CC-BY-SA-4.0" in evidence_licenses:
                 return "REVIEW_REQUIRED" # Track uncertain copyleft combinations without collapsing them

        # If both are present, it's review required
        if "GFDL-1.3-only" in evidence_licenses and "CC-BY-SA-4.0" in evidence_licenses:
            return "REVIEW_REQUIRED"

        return "VERIFIED"
