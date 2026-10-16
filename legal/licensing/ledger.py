import json
import os
import jsonschema
from typing import List, Dict, Any, Tuple

class LedgerAPI:
    def __init__(self, schema_path: str = None):
        if schema_path is None:
            schema_path = os.path.join(os.path.dirname(__file__), 'schema.json')
        with open(schema_path, 'r', encoding='utf-8') as f:
            self.schema = json.load(f)

    def validate_source(self, source: Dict[str, Any]) -> Tuple[bool, str]:
        """Validates a single source against the JSON schema."""
        try:
            jsonschema.validate(instance=source, schema=self.schema)
        except jsonschema.exceptions.ValidationError as e:
            return False, str(e.message)
        return True, ""

    def evaluate(self, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluates a list of sources and returns an overall redistribution eligibility status.
        Result status: 'verified', 'blocked', or 'reviewRequired'.
        """
        if not sources:
            return {"status": "blocked", "reason": "No sources provided."}

        has_cc_by_sa = False
        has_gfdl = False

        reasons = []

        for idx, source in enumerate(sources):
            # First, check schema constraints (this catches missing author, license, source_id, missing declared, etc.)
            is_valid, error_msg = self.validate_source(source)
            if not is_valid:
                return {"status": "blocked", "reason": f"Source at index {idx} failed schema validation: {error_msg}"}

            # Extract license details
            license_info = source.get("license", {})
            declared = license_info.get("declared")
            obligations_met = license_info.get("obligations_met")

            if not declared:
                return {"status": "blocked", "reason": f"Source '{source['source_id']}' has no declared license. Cannot infer Public Domain."}

            if declared in ["CC-BY-SA-4.0", "GFDL-1.3-only"]:
                if not obligations_met:
                    return {"status": "blocked", "reason": f"Source '{source['source_id']}' declares {declared} but obligations are not met."}

                if declared == "CC-BY-SA-4.0":
                    has_cc_by_sa = True
                elif declared == "GFDL-1.3-only":
                    has_gfdl = True

            # If a source says it's PUBLIC-DOMAIN or CC0-1.0 but obligations_met is false, we can still block it or let it pass?
            # The prompt says: "Never infer Public Domain status from a missing license." (Handled by schema/validation)
            # We don't have explicit instructions to block CC0/PD on obligations_met = False, but let's be conservative:
            if declared in ["CC0-1.0", "PUBLIC-DOMAIN"] and not obligations_met:
                 return {"status": "blocked", "reason": f"Source '{source['source_id']}' declares {declared} but obligations/evidence are not met."}

        # Check mixed-source provenance for legal uncertainty
        if has_cc_by_sa and has_gfdl:
            return {"status": "reviewRequired", "reason": "Mixed provenance containing both CC-BY-SA-4.0 and GFDL-1.3-only requires legal review."}

        # If we got here, everything is verified
        return {"status": "verified", "reason": "All sources verified successfully."}
