import typing
import re
from urllib.parse import urlparse
from schema import get_schema

# We will do a basic manual validation according to the schema.
def validate_against_schema(record: dict) -> list[str]:
    errors = []
    schema = get_schema()

    for req in schema["required"]:
        if req not in record:
            errors.append(f"Missing required field: {req}")

    if "author" in record and not record["author"]:
        errors.append("author cannot be empty")

    if "source_id" in record and not record["source_id"]:
        errors.append("source_id cannot be empty")

    if "url" in record:
        parsed = urlparse(record["url"])
        if not parsed.scheme or not parsed.netloc:
            errors.append("url must be a valid URI")

    if "license" in record:
        lic = record["license"]
        if not isinstance(lic, dict):
            errors.append("license must be an object")
        else:
            for req in schema["properties"]["license"]["required"]:
                if req not in lic:
                    errors.append(f"Missing required license field: {req}")

            if "declared_id" in lic:
                allowed_licenses = schema["properties"]["license"]["properties"]["declared_id"]["enum"]
                if lic["declared_id"] not in allowed_licenses:
                    errors.append(f"Invalid license declared_id: {lic['declared_id']}")

            if "evidence_hash" in lic:
                if not re.match(r"^[0-9a-f]{64}$", lic["evidence_hash"]):
                    errors.append(f"evidence_hash does not match pattern: {lic['evidence_hash']}")

            if "evidence_url" in lic:
                parsed = urlparse(lic["evidence_url"])
                if not parsed.scheme or not parsed.netloc:
                    errors.append("evidence_url must be a valid URI")

    return errors

class LicensingLedger:
    def __init__(self):
        self.records = []

    def add_record(self, record: dict):
        self.records.append(record)

    def validate_ledger(self) -> dict[str, str]:
        """
        Validates all records and returns a mapping from source_id to eligibility status.
        Status can be "VERIFIED", "BLOCKED", or "REVIEW_REQUIRED".
        """
        results = {}
        for idx, record in enumerate(self.records):
            source_id = record.get("source_id", f"unknown-{idx}")

            schema_errors = validate_against_schema(record)
            if schema_errors:
                results[source_id] = "BLOCKED"
                continue

            declared_id = record["license"]["declared_id"]
            modification_status = record["modification_status"]

            if declared_id == "PUBLIC-DOMAIN":
                # Public domain must be strictly verified, returning REVIEW_REQUIRED
                # unless proven otherwise.
                results[source_id] = "REVIEW_REQUIRED"
            elif declared_id == "CC-BY-SA-4.0":
                obligations = record["license"].get("cc_by_sa_obligations", {})
                reqs = ["attribution", "license_link", "sharealike", "no_additional_restrictions"]

                if modification_status == "MODIFIED":
                    reqs.append("changes_disclosed")

                if all(obligations.get(req) for req in reqs):
                    results[source_id] = "VERIFIED"
                else:
                    results[source_id] = "REVIEW_REQUIRED"
            elif declared_id == "GFDL-1.3-only":
                obligations = record["license"].get("gfdl_obligations", {})
                reqs = ["license_copy", "copyright_notices", "history"]

                if all(obligations.get(req) for req in reqs):
                    results[source_id] = "VERIFIED"
                else:
                    results[source_id] = "REVIEW_REQUIRED"
            elif declared_id == "CC0-1.0":
                results[source_id] = "VERIFIED"
            elif declared_id == "CC-BY-2.0-FR":
                results[source_id] = "VERIFIED"
            else:
                results[source_id] = "BLOCKED"

        return results

def validate_sources(sources: list[dict]) -> dict[str, str]:
    ledger = LicensingLedger()
    for s in sources:
        ledger.add_record(s)
    return ledger.validate_ledger()
