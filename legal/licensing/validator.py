import json
from pathlib import Path

class LicensingLedgerValidator:
    def __init__(self):
        schema_path = Path(__file__).parent / "schema.json"
        with schema_path.open("r", encoding="utf-8") as f:
            self.schema = json.load(f)

    def validate_record(self, record):
        # 1. Enforce basic required fields presence manually since we use standard library
        for required_field in self.schema.get("required", []):
            if required_field not in record or not record[required_field]:
                return "BLOCKED"

        # 2. Extract fields
        source_id = record.get("source_id")
        author = record.get("author")
        declared_license = record.get("declared_license")
        verified_evidence = record.get("verified_evidence", False)
        url = record.get("url")
        version = record.get("version")
        modification_status = record.get("modification_status")
        co_offered = record.get("co_offered_licenses", [])

        # 3. Reject missing author, license, or source identity
        if not author or not declared_license or not source_id:
            return "BLOCKED"

        # 4. Never infer Public Domain status from a missing license
        # (This is somewhat handled by the requirement for declared_license above)
        if declared_license == "PUBLIC-DOMAIN" and not verified_evidence:
            return "BLOCKED"

        # 5. Check GFDL obligations
        if declared_license == "GFDL-1.3-only":
            if not verified_evidence:
                return "BLOCKED"
            if not version or not modification_status:
                return "BLOCKED"

        # 6. Check CC BY-SA obligations
        if declared_license == "CC-BY-SA-4.0":
            if not url:
                return "BLOCKED"

        # 7. Check changed source versions requirement
        if version and not verified_evidence and declared_license != "PUBLIC-DOMAIN":
            return "REVIEW_REQUIRED"

        # 8. Treat legally uncertain combinations as reviewRequired
        if co_offered:
            if "GFDL-1.3-only" in co_offered and "CC-BY-SA-4.0" in co_offered:
                return "REVIEW_REQUIRED"
            if declared_license == "GFDL-1.3-only" and "CC-BY-SA-4.0" in co_offered:
                return "REVIEW_REQUIRED"
            if declared_license == "CC-BY-SA-4.0" and "GFDL-1.3-only" in co_offered:
                return "REVIEW_REQUIRED"

        # 9. Differentiate license declarations from verified evidence
        if not verified_evidence:
            return "REVIEW_REQUIRED"

        return "VERIFIED"
