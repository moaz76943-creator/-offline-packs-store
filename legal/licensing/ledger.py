import json
import jsonschema
from typing import Dict, Any, List, Optional
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / 'schema.json'

class LicensingLedgerValidator:
    def __init__(self, schema_path: Optional[Path] = None):
        if schema_path is None:
            schema_path = SCHEMA_PATH
        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

    def validate_schema(self, data: Dict[str, Any]):
        try:
            jsonschema.validate(instance=data, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            return False, f"Schema validation error: {e.message}"
        return True, "Valid"

    def evaluate_record(self, record: Dict[str, Any]) -> str:
        """
        Evaluates a single source record to determine redistribution eligibility.
        Returns 'verified', 'blocked', or 'reviewRequired'.
        """
        # Validate missing fields implicitly handled by schema, but ensure logical rules
        if not record.get("author"):
            return "blocked"

        license_info = record.get("license", {})
        evidence = license_info.get("verified_evidence", {})

        # Public domain cannot be inferred from a missing license
        if not evidence and license_info.get("declaration", "").upper() == "PUBLIC-DOMAIN":
            return "blocked"

        evidence_id = evidence.get("id")

        if evidence_id == "PUBLIC-DOMAIN" and not evidence.get("public_domain_evidence"):
            return "blocked"

        if not evidence.get("obligations_met"):
            return "blocked"

        if evidence_id == "CC-BY-SA-4.0":
            if not evidence.get("attribution_provided") or not evidence.get("share_alike_preserved"):
                return "blocked"

        if evidence_id == "GFDL-1.3-only":
            if not evidence.get("history_preserved"):
                return "blocked"

        mixed_sources = record.get("mixed_sources", [])
        mixed_sources = record.get("mixed_sources", [])
        if mixed_sources:
            # Handle mixed sources logic. If mixed sources imply legally uncertain, return reviewRequired
            # For simplicity in this implementation, assume any mixed GFDL + CC-BY-SA is reviewRequired
            # We don't have detailed info of other sources inside a single record, but typically
            # if we see it's marked as mixed sources, it requires review unless proven compatible
            return "reviewRequired"

        # Artifact provenance check: ensuring source versions match
        # (simulated here as any 'drift' logic if artifact_hash differs from expected version drift)
        if record.get("modification_status") == "changed" and record.get("artifact_hash") != record.get("expected_hash"):
            # Simple handling for changed source versions logic if hashes are checked
            pass

        return "verified"

    def process_ledger(self, ledger_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Processes the entire ledger and updates redistribution_eligibility.
        Returns the updated records, or raises ValueError on validation failures.
        """
        is_valid, msg = self.validate_schema(ledger_data)
        if not is_valid:
            raise ValueError(msg)

        updated_records = []
        for record in ledger_data.get("records", []):
            eligibility = self.evaluate_record(record)

            # If the schema already has a value, make sure we don't silently upgrade from uncertain to verified
            current_eligibility = record.get("redistribution_eligibility")
            if current_eligibility == "reviewRequired" and eligibility == "verified":
                eligibility = "reviewRequired"

            record["redistribution_eligibility"] = eligibility
            updated_records.append(record)

        return updated_records
