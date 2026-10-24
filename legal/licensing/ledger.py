import json
from legal.ledger.admission import LICENSES, OBLIGATIONS

LEDGER_SCHEMA = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "url": {"type": "string"},
        "author": {"type": "string"},
        "version": {"type": "string"},
        "license": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "declarations": {"type": "array", "items": {"type": "string"}},
                "verified_evidence": {"type": "boolean"},
                "obligations_met": {"type": "boolean"}
            },
            "required": ["id", "verified_evidence"]
        },
        "modification_status": {"type": "string"},
        "artifact_hash": {"type": "string"}
    },
    "required": ["source_id", "url", "author", "version", "license"]
}

def validate_schema(instance, schema):
    if schema.get("type") == "object":
        if not isinstance(instance, dict):
            raise ValueError(f"Expected object, got {type(instance)}")
        for req in schema.get("required", []):
            if req not in instance:
                raise ValueError(f"Missing required field: {req}")
        for prop, prop_schema in schema.get("properties", {}).items():
            if prop in instance:
                validate_schema(instance[prop], prop_schema)
    elif schema.get("type") == "array":
        if not isinstance(instance, list):
            raise ValueError(f"Expected array, got {type(instance)}")
        item_schema = schema.get("items")
        if item_schema:
            for item in instance:
                validate_schema(item, item_schema)
    elif schema.get("type") == "string":
        if not isinstance(instance, str):
            raise ValueError(f"Expected string, got {type(instance)}")
    elif schema.get("type") == "boolean":
        if not isinstance(instance, bool):
            raise ValueError(f"Expected boolean, got {type(instance)}")

class LicensingLedger:
    def __init__(self):
        self.records = {}

    def add(self, record):
        validate_schema(record, LEDGER_SCHEMA)

        if not record.get("author"):
            raise ValueError("Missing author")

        lic = record["license"]

        if lic["id"] not in LICENSES:
             raise ValueError(f"Unknown license identifier: {lic['id']}")

        if lic["id"] == "PUBLIC-DOMAIN" and not lic.get("verified_evidence"):
            raise ValueError("Public domain requires verified evidence")

        self.records[record["source_id"]] = record

    def evaluate(self, source_ids):
        if not source_ids:
            return "verified"

        licenses = set()
        for sid in source_ids:
            if sid not in self.records:
                return "blocked"
            record = self.records[sid]

            # Check obligations
            lic = record["license"]
            if not lic.get("verified_evidence"):
                return "reviewRequired"

            if lic["id"] in OBLIGATIONS and not lic.get("obligations_met"):
                return "blocked"

            licenses.add(lic["id"])

        # check mixing copyleft
        # OBLIGATIONS dictionary can be used to distinguish copyleft from permissive
        # CC-BY-SA and GFDL are both copyleft with different terms.
        copyleft_licenses = {l for l in licenses if l in OBLIGATIONS and ('sharealike' in OBLIGATIONS[l] or 'history' in OBLIGATIONS[l])}

        if len(copyleft_licenses) > 1:
            return "reviewRequired"

        return "verified"
