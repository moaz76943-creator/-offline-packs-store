import json

try:
    from legal.ledger.admission import LICENSES, OBLIGATIONS
except ImportError:
    from ..ledger.admission import LICENSES, OBLIGATIONS

LEDGER_SCHEMA = {
    "type": "object",
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string"},
                    "url": {"type": "string"},
                    "author": {"type": "string"},
                    "version": {"type": "string"},
                    "license": {
                        "type": "object",
                        "properties": {
                            "declared": {"type": "string"},
                            "evidence_verified": {"type": "boolean"},
                            "obligations": {"type": "array"}
                        },
                        "required": ["declared"]
                    },
                    "modification_status": {"type": "string"},
                    "artifact_hash": {"type": "string"}
                },
                "required": ["source_id", "url", "author", "version", "license", "modification_status"]
            }
        }
    },
    "required": ["sources"]
}

class LicensingLedger:
    def __init__(self):
        self.sources = {}

    def _is_string(self, value):
        return isinstance(value, str) and bool(value.strip())

    def validate_schema(self, source: dict) -> bool:
        if not isinstance(source, dict):
            return False

        required_fields = ["source_id", "url", "author", "version", "license", "modification_status"]
        for field in required_fields:
            if field not in source:
                return False

        if not self._is_string(source["source_id"]):
            return False
        if not self._is_string(source["url"]):
            return False
        if not self._is_string(source["author"]):
            return False
        if not self._is_string(source["version"]):
            return False
        if not self._is_string(source["modification_status"]):
            return False

        if not isinstance(source["license"], dict):
            return False

        if "declared" not in source["license"]:
            return False

        if not self._is_string(source["license"]["declared"]):
            return False

        if "obligations" in source["license"] and not isinstance(source["license"]["obligations"], list):
            return False

        if "evidence_verified" in source["license"] and not isinstance(source["license"]["evidence_verified"], bool):
            return False

        return True

    def evaluate_source(self, source: dict) -> str:
        if not self.validate_schema(source):
            return "blocked"

        declared_license = source["license"]["declared"]
        if declared_license not in LICENSES:
            return "blocked"

        evidence_verified = source["license"].get("evidence_verified", False)

        if declared_license == "PUBLIC-DOMAIN" and not evidence_verified:
            # Never infer Public Domain status from a missing license or unverified evidence
            return "blocked"

        obligations = set(source["license"].get("obligations", []))
        if declared_license in OBLIGATIONS:
            expected_obligations = set(OBLIGATIONS[declared_license])
            if not expected_obligations.issubset(obligations):
                return "blocked"

        if not evidence_verified:
            return "reviewRequired"

        return "verified"

    def evaluate_combination(self, sources: list) -> str:
        if not isinstance(sources, list) or not sources:
            return "blocked"

        statuses = set()
        copyleft_licenses = set()

        for source in sources:
            status = self.evaluate_source(source)
            statuses.add(status)
            if status == "blocked":
                return "blocked"

            declared_license = source["license"]["declared"]
            # Identify copyleft licenses (GFDL-1.3-only and CC-BY-SA-4.0 require sharealike / history which are copyleft)
            if declared_license in ("CC-BY-SA-4.0", "GFDL-1.3-only"):
                copyleft_licenses.add(declared_license)

        if len(copyleft_licenses) > 1:
            return "blocked"

        if "reviewRequired" in statuses:
            return "reviewRequired"

        return "verified"

    def add_source(self, source: dict) -> str:
        status = self.evaluate_source(source)
        if status in ("verified", "reviewRequired"):
            # Avoid rewriting source license claims automatically, store a copy or just reference
            # maintain actual source hashes when artifacts exist.
            self.sources[source["source_id"]] = source.copy()
        return status
