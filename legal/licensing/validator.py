import json
import os
from typing import Dict, Any

class LicensingLedgerValidator:
    def __init__(self, schema_path: str = None):
        if schema_path is None:
            schema_path = os.path.join(os.path.dirname(__file__), "schema.json")
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def _validate_schema(self, record: Dict[str, Any]) -> bool:
        # Simplistic schema validation (since we're only using stdlib)
        required_fields = ["source_id", "url", "author", "version", "license", "modification_status"]
        for field in required_fields:
            if field not in record:
                return False

        license_info = record.get("license", {})
        if not isinstance(license_info, dict):
            return False

        if "declared" not in license_info or "evidence" not in license_info:
            return False

        mod_status = record.get("modification_status")
        if mod_status not in ["unmodified", "modified", "derivative"]:
            return False

        return True

    def validate_record(self, record: Dict[str, Any]) -> str:
        if not self._validate_schema(record):
            return "BLOCKED"

        license_info = record.get("license", {})
        declared = license_info.get("declared", "")
        evidence = license_info.get("evidence", "")

        # Never infer Public Domain status from a missing license or evidence
        if declared.lower() in ["public domain", "cc0", "pd"]:
            if not evidence:
                return "BLOCKED"

        if not declared or not evidence:
            return "BLOCKED"

        # Explicitly fail inferred Public Domain scenario
        if not declared and not evidence:
            return "BLOCKED"

        # Treat legally uncertain combinations as reviewRequired
        if declared != evidence:
            # E.g., if one says CC BY-SA and evidence points to a slightly different copyleft, require review
            return "REVIEW_REQUIRED"

        # Treat uncertain copyleft combinations as REVIEW_REQUIRED
        mod_status = record.get("modification_status")
        uncertain_copyleft = ["cc by-sa 3.0", "cc by-sa", "cc by-nc-sa", "gpl"]
        if any(c in declared.lower() for c in uncertain_copyleft) and mod_status == "derivative":
            return "REVIEW_REQUIRED"

        # Basic validations
        # Add logic to check specific license constraints if needed
        # CC BY-SA, GFDL, etc...

        # If everything passes and evidence matches declaration
        return "VERIFIED"

    def validate_ledger(self, ledger: Dict[str, Any]) -> Dict[str, str]:
        results = {}
        records = ledger.get("records", [])
        for record in records:
            source_id = record.get("source_id", "unknown")
            results[source_id] = self.validate_record(record)
        return results
