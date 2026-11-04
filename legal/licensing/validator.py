from typing import Dict, Any

class LicensingValidator:
    def evaluate(self, record: Dict[str, Any]) -> str:
        # Mandatory fields
        required_fields = ["source_id", "url", "author", "version", "license", "modification_status"]
        for field in required_fields:
            val = record.get(field)
            if val is None:
                return "blocked"
            if isinstance(val, str) and not val.strip():
                return "blocked"

        license_info = record.get("license")
        if not isinstance(license_info, dict):
            return "blocked"

        declaration = license_info.get("declaration")
        evidence = license_info.get("verified_evidence")

        if not declaration or not evidence:
            # Never infer Public Domain status from a missing license
            return "blocked"

        decl_str = str(declaration).upper()

        # Preserve mixed-source provenance without collapsing licenses
        has_gfdl = "GFDL" in decl_str
        has_cc_by_sa = "CC BY-SA" in decl_str or "CC-BY-SA" in decl_str

        # Treat legally uncertain combinations as reviewRequired
        if has_gfdl and has_cc_by_sa:
            return "reviewRequired"

        known_licenses = ["CC BY-SA", "CC-BY-SA", "GFDL", "PUBLIC DOMAIN", "CC0", "MIT", "APACHE", "CC BY"]
        if not any(k in decl_str for k in known_licenses):
            return "reviewRequired"

        obligations = license_info.get("obligations", {})

        if has_cc_by_sa:
            attr = obligations.get("attribution_met", False)
            sa = obligations.get("share_alike_met", False)
            if not attr or not sa:
                return "reviewRequired"

        if has_gfdl:
            history = obligations.get("history_preserved", False)
            if not history:
                return "reviewRequired"

        return "verified"
