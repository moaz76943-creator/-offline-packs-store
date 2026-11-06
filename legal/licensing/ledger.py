import jsonschema
from legal.licensing.schema import LEDGER_SCHEMA

class LicensingLedgerValidator:
    def __init__(self):
        self.schema = LEDGER_SCHEMA

    def validate_record(self, record):
        try:
            jsonschema.validate(instance=record, schema=self.schema, format_checker=jsonschema.FormatChecker())
        except jsonschema.exceptions.ValidationError as e:
            return {"status": "BLOCKED", "reason": str(e)}

        # Missing license block logic is handled by schema (required fields).
        # We never infer public domain if license is missing (schema enforcing).

        return {"status": "VERIFIED", "reason": ""}

    def evaluate_mixed_sources(self, records):
        """
        Preserves mixed-source provenance without collapsing licenses.
        Evaluates combination rules: legally uncertain combinations are reviewRequired.
        """
        licenses = set()
        for record in records:
            res = self.validate_record(record)
            if res["status"] != "VERIFIED":
                return {"status": "BLOCKED", "reason": f"Invalid record: {res['reason']}"}
            licenses.add(record["license"]["declared_id"])

        versions = set()
        for record in records:
            versions.add(record["version"])

        # Evaluate combinations. If we have CC-BY-SA and GFDL without dual-licensing, or other mixed ones
        if len(licenses) > 1:
            # We treat uncertain combinations as reviewRequired.
            # CC-BY-SA-4.0 and GFDL-1.3-only generally conflict if strictly mixed without co-offering
            # For this simple exercise, mixed licenses -> reviewRequired
            # But let's check some safe combos. Actually, most combos are uncertain.
            return {"status": "REVIEW_REQUIRED", "reason": "Mixed licenses"}

        if len(versions) > 1:
            return {"status": "REVIEW_REQUIRED", "reason": "Mixed source versions"}

        if len(licenses) == 0:
             return {"status": "BLOCKED", "reason": "No licenses found"}

        return {"status": "VERIFIED", "reason": ""}
