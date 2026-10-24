from legal.ledger.admission import LICENSES, OBLIGATIONS
import re

# We define the schema conceptually to be implemented via a custom validator
LEDGER_SCHEMA = {
    "type": "object",
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "minLength": 1},
                    "url": {"type": "string", "minLength": 1, "format": "uri"},
                    "author": {"type": "string", "minLength": 1},
                    "version": {"type": "string", "minLength": 1},
                    "license": {"type": "string", "enum": list(LICENSES)},
                    "modification_status": {"type": "string"},
                    "artifact_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                    "verified_evidence": {"type": "boolean"},
                },
                "required": ["source_id", "url", "author", "version", "license", "modification_status"]
            }
        },
        "output_license": {"type": "string", "enum": list(LICENSES)},
        "compliance": {
            "type": "object",
            "additionalProperties": {"type": "boolean"}
        }
    },
    "required": ["sources", "output_license"]
}

class LicensingLedger:
    def __init__(self, ledger_data):
        self.ledger_data = ledger_data

    def validate_schema(self):
        if not isinstance(self.ledger_data, dict):
            return False

        if "sources" not in self.ledger_data or "output_license" not in self.ledger_data:
            return False

        sources = self.ledger_data["sources"]
        if not isinstance(sources, list):
            return False

        for source in sources:
            if not isinstance(source, dict):
                return False

            required_keys = ["source_id", "url", "author", "version", "license", "modification_status"]
            for key in required_keys:
                if key not in source:
                    return False
                if not isinstance(source[key], str) or len(source[key]) == 0:
                    return False

            if source["license"] not in LICENSES:
                return False

            if "artifact_hash" in source:
                if not isinstance(source["artifact_hash"], str):
                    return False
                if not re.match(r"^[0-9a-f]{64}$", source["artifact_hash"]):
                    return False

            if "verified_evidence" in source:
                if not isinstance(source["verified_evidence"], bool):
                    return False

        output_license = self.ledger_data["output_license"]
        if output_license not in LICENSES:
            return False

        if "compliance" in self.ledger_data:
            if not isinstance(self.ledger_data["compliance"], dict):
                return False
            for k, v in self.ledger_data["compliance"].items():
                if not isinstance(v, bool):
                    return False

        return True

    def evaluate_combination(self, usage=None):
        if not self.validate_schema():
            return "blocked"

        sources = self.ledger_data["sources"]
        output_license = self.ledger_data["output_license"]
        compliance = self.ledger_data.get("compliance", {})

        copyleft_licenses = set()

        # Explicit copyleft licenses based on OBLIGATIONS definition in admission.py
        COPYLEFT = {"CC-BY-SA-4.0", "GFDL-1.3-only"}

        for source in sources:
            lic = source["license"]

            # Check for unverified PD status
            if lic == "PUBLIC-DOMAIN" and not source.get("verified_evidence"):
                return "reviewRequired"

            if lic in COPYLEFT:
                copyleft_licenses.add(lic)

            if lic not in OBLIGATIONS and lic not in ["PUBLIC-DOMAIN", "CC0-1.0"]:
                # Unknown or proprietary license (e.g. legally uncertain combinations)
                return "reviewRequired"

            if usage and source["source_id"] in usage:
                source_usage = usage[source["source_id"]]
                if source_usage.get("version") != source["version"]:
                    return "reviewRequired"
                if "artifact_hash" in source and source_usage.get("artifact_hash") != source["artifact_hash"]:
                    return "reviewRequired"
                if "manual_review" in source_usage and not source_usage["manual_review"]:
                     return "reviewRequired"

        if len(copyleft_licenses) > 1:
            return "blocked" # Mixed copyleft

        # Check obligations for ALL licenses that have them
        for source in sources:
            lic = source["license"]
            if lic in OBLIGATIONS:
                reqs = OBLIGATIONS[lic]
                for req in reqs:
                    if not compliance.get(req):
                        return "blocked"

        # Cannot relicense copyleft
        for lic in copyleft_licenses:
            if output_license != lic:
                return "blocked"

        if not copyleft_licenses and sources and output_license == "PUBLIC-DOMAIN":
            if any(s["license"] != "PUBLIC-DOMAIN" for s in sources):
                return "blocked"

        return "verified"