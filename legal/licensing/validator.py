from typing import Dict, Any, List, Optional

class LicensingLedgerValidator:
    """Validates source-specific licensing records and determines redistribution eligibility."""

    VALID_LICENSE_IDS = {
        "CC-BY-SA-4.0", "CC-BY-SA-3.0", "GFDL-1.3-only",
        "CC0-1.0", "PUBLIC-DOMAIN", "CC-BY-4.0", "MIT", "OdbL-1.0"
    }

    COPYLEFT_LICENSES = {
        "CC-BY-SA-4.0", "CC-BY-SA-3.0", "GFDL-1.3-only", "OdbL-1.0"
    }

    @staticmethod
    def _validate_dict_types(data: Dict, expected: Dict[str, type]) -> List[str]:
        issues = []
        for key, typ in expected.items():
            if key not in data:
                issues.append(f"Missing required field: {key}")
            elif not isinstance(data[key], typ):
                issues.append(f"Field '{key}' must be of type {typ.__name__}")
        return issues

    def validate_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Validates a single source licensing record."""
        issues = self._validate_dict_types(record, {
            "source_id": str,
            "url": str,
            "author": str,
            "version": str,
            "modification_status": str,
            "license": dict
        })

        if issues:
            return {"status": "BLOCKED", "issues": issues}

        if not record["source_id"].strip():
            return {"status": "BLOCKED", "issues": ["source_id cannot be empty"]}

        if not record["author"].strip():
            return {"status": "BLOCKED", "issues": ["author cannot be empty"]}

        if record["modification_status"] not in ("unmodified", "modified"):
            return {"status": "BLOCKED", "issues": ["Invalid modification_status"]}

        license_data = record["license"]
        lic_issues = self._validate_dict_types(license_data, {
            "declared": str,
            "evidence": dict
        })
        if lic_issues:
            return {"status": "BLOCKED", "issues": lic_issues}

        evidence = license_data["evidence"]
        ev_issues = self._validate_dict_types(evidence, {"id": str})
        if ev_issues:
            return {"status": "BLOCKED", "issues": ev_issues}

        license_id = evidence["id"]
        if license_id not in self.VALID_LICENSE_IDS:
            return {"status": "BLOCKED", "issues": [f"Unknown license identifier: {license_id}"]}

        # Validate CC BY-SA obligations
        if license_id.startswith("CC-BY-SA") or license_id.startswith("CC-BY"):
            if not record["author"].strip() or record["author"] == "Unknown":
                return {"status": "BLOCKED", "issues": [f"{license_id} requires explicit attribution (author)"]}
            if not record["url"].strip():
                return {"status": "BLOCKED", "issues": [f"{license_id} requires a source URL for attribution"]}

        # Validate GFDL obligations
        if license_id == "GFDL-1.3-only":
            if not record["author"].strip() or record["author"] == "Unknown":
                return {"status": "BLOCKED", "issues": ["GFDL requires explicit attribution (author)"]}
            if not record["url"].strip():
                return {"status": "BLOCKED", "issues": ["GFDL requires a source URL"]}

        # Never infer Public Domain from a missing license
        if not license_data["declared"].strip() and license_id == "PUBLIC-DOMAIN":
            return {"status": "BLOCKED", "issues": ["Public Domain status cannot be inferred from a missing declared license"]}

        return {"status": "VERIFIED", "issues": []}

    def evaluate_mixed_provenance(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Evaluates redistribution eligibility for a mix of sources."""
        all_issues = []
        copyleft_licenses_seen = set()

        if not records:
            return {"status": "BLOCKED", "issues": ["No sources provided for mixed provenance evaluation"]}

        for idx, record in enumerate(records):
            result = self.validate_record(record)
            if result["status"] == "BLOCKED":
                all_issues.extend([f"Record {idx}: {issue}" for issue in result["issues"]])
            else:
                license_id = record["license"]["evidence"]["id"]
                if license_id in self.COPYLEFT_LICENSES:
                    copyleft_licenses_seen.add(license_id)

        if all_issues:
            return {"status": "BLOCKED", "issues": all_issues}

        if len(copyleft_licenses_seen) > 1:
            return {
                "status": "REVIEW_REQUIRED",
                "issues": [f"Mixed copyleft licenses detected: {', '.join(copyleft_licenses_seen)}"],
                "reason": "Legally uncertain combinations are treated as review required."
            }

        return {"status": "VERIFIED", "issues": []}
