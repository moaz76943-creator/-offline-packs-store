import json
import jsonschema
from typing import Dict, Any, List
from legal.ledger.admission import LICENSES, OBLIGATIONS

LEDGER_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Lexical Source Licensing Ledger",
    "type": "object",
    "required": ["records"],
    "properties": {
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "source_id", "url", "author", "version",
                    "license", "modification_status"
                ],
                "properties": {
                    "source_id": {"type": "string", "minLength": 1},
                    "url": {"type": "string", "format": "uri", "pattern": "^https://"},
                    "author": {"type": "string", "minLength": 1},
                    "version": {"type": "string", "minLength": 1},
                    "license": {
                        "type": "object",
                        "required": ["id", "declaration_only"],
                        "properties": {
                            "id": {"type": "string", "enum": list(LICENSES)},
                            "declaration_only": {"type": "boolean"},
                            "evidence_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                            "provided_obligations": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        }
                    },
                    "modification_status": {
                        "type": "string",
                        "enum": ["unmodified", "modified"]
                    }
                }
            }
        }
    }
}

class LicensingLedger:
    def __init__(self):
        self.records: Dict[str, List[Dict[str, Any]]] = {}

    def load_records(self, data: Dict[str, Any]) -> None:
        jsonschema.validate(instance=data, schema=LEDGER_SCHEMA)
        for record in data["records"]:
            self.add_record(record)

    def add_record(self, record: Dict[str, Any]) -> Dict[str, str]:
        for field in ["source_id", "url", "author", "version", "license", "modification_status"]:
            if field not in record:
                return {"status": "BLOCKED", "reason": f"missing {field}"}

        sid = record["source_id"]
        lic = record["license"]

        if "id" not in lic or "declaration_only" not in lic:
            return {"status": "BLOCKED", "reason": "invalid license block"}

        lid = lic["id"]
        if lid not in LICENSES:
            return {"status": "BLOCKED", "reason": f"unknown license {lid}"}

        if lid == "PUBLIC-DOMAIN" and lic.get("declaration_only", True):
            return {"status": "BLOCKED", "reason": "public domain requires verified evidence, never inferred"}

        # Check required obligations
        provided_obligations = set(lic.get("provided_obligations", []))
        required_obligations = set(OBLIGATIONS.get(lid, ()))

        missing_obligations = required_obligations - provided_obligations
        if missing_obligations:
            return {"status": "BLOCKED", "reason": f"missing obligations: {missing_obligations}"}

        if sid not in self.records:
            self.records[sid] = []

        self.records[sid].append(record)
        return {"status": "VERIFIED", "reason": "added"}

    def evaluate_combination(self, source_ids: List[str], target_license: str, target_version: Dict[str, str] = None) -> Dict[str, str]:
        if target_license not in LICENSES:
            return {"status": "BLOCKED", "reason": f"unknown target license {target_license}"}

        missing = [sid for sid in source_ids if sid not in self.records]
        if missing:
            return {"status": "BLOCKED", "reason": f"missing sources: {missing}"}

        source_licenses = []
        for sid in source_ids:
            records_for_source = self.records[sid]
            # Use specific version if provided, otherwise latest
            version_to_use = target_version.get(sid) if target_version else None
            selected_record = None
            if version_to_use:
                selected_record = next((r for r in records_for_source if r["version"] == version_to_use), None)
                if not selected_record:
                    return {"status": "BLOCKED", "reason": f"changed source version not found: {sid} v{version_to_use}"}
            else:
                selected_record = records_for_source[-1]

            source_licenses.append(selected_record["license"]["id"])

            # Additional provenance checks
            if selected_record["license"]["id"] == "GFDL-1.3-only":
                provided = set(selected_record["license"].get("provided_obligations", []))
                if "history" not in provided or "license_copy" not in provided:
                    return {"status": "BLOCKED", "reason": f"incomplete GFDL provenance for {sid}"}

        # Check copyleft combinations
        copyleft_licenses = {lid for lid in source_licenses if lid in ["CC-BY-SA-4.0", "GFDL-1.3-only"]}

        if len(copyleft_licenses) > 1:
            return {"status": "REVIEW_REQUIRED", "reason": "mixed copyleft licenses cannot be combined automatically"}

        if copyleft_licenses:
            copyleft_lid = list(copyleft_licenses)[0]
            if target_license != copyleft_lid:
                return {"status": "REVIEW_REQUIRED", "reason": f"copyleft {copyleft_lid} cannot be re-licensed to {target_license}"}

        if target_license == "PUBLIC-DOMAIN" and any(lid != "PUBLIC-DOMAIN" for lid in source_licenses):
             return {"status": "REVIEW_REQUIRED", "reason": "cannot release non-PD sources as PD"}

        # Other mixed licenses
        if len(set(source_licenses)) > 1:
            if not all(lid in ["CC0-1.0", "PUBLIC-DOMAIN"] for lid in source_licenses if lid != target_license):
                return {"status": "REVIEW_REQUIRED", "reason": "legally uncertain combination"}

        return {"status": "VERIFIED", "reason": "redistribution clear"}
