from copy import deepcopy
import re

try:
    from legal.ledger.admission import LICENSES, OBLIGATIONS, url_ok
except ImportError:
    from ..ledger.admission import LICENSES, OBLIGATIONS, url_ok

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
        if not url_ok(source["url"]):
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

        if "obligations" in source["license"]:
            obligations = source["license"]["obligations"]
            if not isinstance(obligations, list) or any(not self._is_string(item) for item in obligations):
                return False

        # A supplied artifact digest must be a real SHA-256, never an arbitrary label.
        if "artifact_hash" in source:
            digest = source["artifact_hash"]
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
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

    def evaluate_combination(self, sources: list, *, output_license=None, expected_versions=None, expected_artifact_hashes=None) -> str:
        """Check claimed source compatibility, never authorize publication.

        Release approval remains exclusively with legal.ledger.admission,
        which verifies original source bytes, license evidence and reviews.
        A caller may pin every input version, immutable artifact SHA-256, and the proposed output license.
        """
        if not isinstance(sources, list) or not sources:
            return "blocked"
        if output_license is not None and output_license not in LICENSES:
            return "blocked"
        if expected_versions is not None and not isinstance(expected_versions, dict):
            return "blocked"
        if expected_artifact_hashes is not None and not isinstance(expected_artifact_hashes, dict):
            return "blocked"

        statuses = set()
        copyleft_licenses = set()
        seen_ids = set()

        for source in sources:
            status = self.evaluate_source(source)
            statuses.add(status)
            if status == "blocked":
                return "blocked"
            source_id = source["source_id"]
            if source_id in seen_ids:
                return "blocked"
            seen_ids.add(source_id)
            if expected_versions is not None and expected_versions.get(source_id) != source["version"]:
                return "blocked"
            if expected_artifact_hashes is not None:
                # A missing digest must not match a missing expectation.
                actual_hash = source.get("artifact_hash")
                if (not isinstance(actual_hash, str) or
                        re.fullmatch(r"[0-9a-f]{64}", actual_hash) is None or
                        expected_artifact_hashes.get(source_id) != actual_hash):
                    return "blocked"

            declared_license = source["license"]["declared"]
            if declared_license in ("CC-BY-SA-4.0", "GFDL-1.3-only"):
                copyleft_licenses.add(declared_license)

            if output_license is not None:
                # Mirror the canonical admission gate's fail-closed rule:
                # attribution/copyleft sources cannot silently be relicensed.
                if declared_license in OBLIGATIONS and output_license != declared_license:
                    return "blocked"
                if output_license == "PUBLIC-DOMAIN" and declared_license != "PUBLIC-DOMAIN":
                    return "blocked"

        if expected_versions is not None and set(expected_versions) != seen_ids:
            return "blocked"
        if expected_artifact_hashes is not None and set(expected_artifact_hashes) != seen_ids:
            return "blocked"
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
            source_id = source["source_id"]
            # Never silently replace one source identity with incompatible rights/provenance.
            if source_id in self.sources and self.sources[source_id] != source:
                return "blocked"
            self.sources[source_id] = deepcopy(source)
        return status
