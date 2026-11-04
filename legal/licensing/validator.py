import json
import os

class LicensingLedgerValidator:
    def __init__(self, schema_path=None):
        if schema_path is None:
            schema_path = os.path.join(os.path.dirname(__file__), "schema.json")
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def _validate_schema(self, record):
        required = self.schema.get("required", [])
        for req in required:
            if req not in record:
                return False
            # Allow booleans and handle strings
            if isinstance(record[req], str) and not record[req].strip():
                return False

        properties = self.schema.get("properties", {})
        for key, val in record.items():
            if key not in properties:
                continue
            prop_def = properties[key]
            if prop_def.get("type") == "string" and not isinstance(val, str):
                return False
            if prop_def.get("type") == "boolean" and not isinstance(val, bool):
                return False
            if prop_def.get("type") == "object":
                if not isinstance(val, dict):
                    return False
                obj_req = prop_def.get("required", [])
                for orq in obj_req:
                    if orq not in val:
                        return False
                    if isinstance(val[orq], str) and not val[orq].strip():
                        return False
        return True

    def validate(self, record):
        # Check basic schema (missing required fields)
        if not self._validate_schema(record):
            return "BLOCKED"

        license_info = record.get("license", {})
        declared = license_info.get("declared", "").strip()
        evidence = license_info.get("evidence", "").strip()

        # Missing license declaration
        if not declared:
            return "BLOCKED"

        # Reject inferred Public Domain
        if declared.lower() == "public domain" and not evidence:
            return "BLOCKED"

        # Incomplete CC BY-SA obligations
        if "cc by-sa" in declared.lower():
            if not record.get("obligations_met", False):
                return "BLOCKED"

        # GFDL provenance
        if "gfdl" in declared.lower():
            if not evidence:
                return "BLOCKED"

        # Uncertain copyleft combinations
        if "+" in declared or " and " in declared.lower():
            # If evidence is not strong or it's a mix of copyleft licenses
            return "REVIEW_REQUIRED"

        # Evidence must exist if required by standard
        if not evidence and declared.lower() not in ["mit", "bsd"]:
            # Need some evidence for most licenses
            return "REVIEW_REQUIRED"

        return "VERIFIED"
