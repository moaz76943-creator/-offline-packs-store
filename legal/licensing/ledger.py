import json
import jsonschema
from legal.ledger.admission import LICENSES, OBLIGATIONS

LEDGER_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "minLength": 1},
                    "origin_url": {"type": "string"},
                    "author": {"type": "string", "minLength": 1},
                    "version": {"type": "string"},
                    "license": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "evidence_verified": {"type": "boolean"},
                            "obligations_met": {
                                "type": "object",
                                "additionalProperties": {"type": "boolean"}
                            }
                        }
                    },
                    "modification_status": {"type": "string"},
                    "artifact_hash": {"type": "string"}
                },
                "required": ["source_id", "author"]
            }
        },
        "combinations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "source_ids": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "output_license": {"type": "string"}
                },
                "required": ["id", "source_ids", "output_license"]
            }
        }
    },
    "required": ["sources"]
}

def is_copyleft(license_id):
    obs = OBLIGATIONS.get(license_id, [])
    return 'sharealike' in obs or 'history' in obs

class LicensingLedger:
    def __init__(self, data):
        jsonschema.validate(instance=data, schema=LEDGER_SCHEMA)
        self.data = data
        self.sources = {s["source_id"]: s for s in data["sources"]}

    def evaluate_source(self, source_id, expected_version=None):
        if source_id not in self.sources:
            return {"status": "blocked", "reason": "unknown source"}

        source = self.sources[source_id]

        if expected_version and source.get("version") != expected_version:
            return {"status": "blocked", "reason": "changed source version"}

        license_info = source.get("license")
        if not license_info or not license_info.get("id"):
            return {"status": "blocked", "reason": "missing license claim cannot infer Public Domain"}

        license_id = license_info.get("id")
        if license_id not in LICENSES:
            return {"status": "blocked", "reason": "unknown license"}

        if not license_info.get("evidence_verified"):
            if license_id in ["PUBLIC-DOMAIN", "CC0-1.0"]:
                return {"status": "blocked", "reason": "unverified public domain inference"}
            return {"status": "reviewRequired", "reason": "unverified license evidence"}

        if license_id in OBLIGATIONS:
            obligations_met = license_info.get("obligations_met", {})
            for req in OBLIGATIONS[license_id]:
                if not obligations_met.get(req):
                    return {"status": "blocked", "reason": f"missing obligation: {req}"}

        return {"status": "verified"}

    def evaluate_combination(self, combination):
        source_ids = combination.get("source_ids", [])
        output_license = combination.get("output_license")

        if output_license not in LICENSES:
            return {"status": "blocked", "reason": "unknown output license"}

        has_review_required = False
        for sid in source_ids:
            res = self.evaluate_source(sid)
            if res["status"] == "blocked":
                return res
            if res["status"] == "reviewRequired":
                has_review_required = True

        copyleft_licenses = set()
        for sid in source_ids:
            source = self.sources[sid]
            license_id = source["license"]["id"]
            if is_copyleft(license_id):
                copyleft_licenses.add(license_id)

            if license_id in OBLIGATIONS and output_license in ["PUBLIC-DOMAIN", "CC0-1.0"]:
                return {"status": "blocked", "reason": f"cannot downgrade {license_id} to {output_license}"}

        if len(copyleft_licenses) > 1:
            return {"status": "blocked", "reason": "invalid copyleft mixture"}

        for sid in source_ids:
            source = self.sources[sid]
            license_id = source["license"]["id"]
            if is_copyleft(license_id):
                if output_license != license_id:
                    return {"status": "blocked", "reason": f"strict copyleft mismatch: {license_id} cannot be relicensed to {output_license}"}

        if has_review_required:
            return {"status": "reviewRequired", "reason": "some sources require review or uncertain combos"}

        return {"status": "verified"}
