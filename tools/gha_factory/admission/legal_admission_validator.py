from typing import Dict, Any, List, Tuple

MANDATORY_FIELDS = [
    "source_id",
    "license",
    "license_url",
    "upstream_url",
    "snapshot_date",
    "sha256",
    "attribution_text",
    "commercial_use_allowed",
    "share_alike_required",
    "modification_allowed",
    "legal_review_status",
]

ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-SA-3.0", "MIT", "Apache-2.0"}

def validate_source_entry(entry: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []
    for field in MANDATORY_FIELDS:
        if field not in entry:
            errors.append(f"Missing mandatory field: {field}")
        elif entry[field] is None or entry[field] == "":
            errors.append(f"Empty mandatory field: {field}")

    license_val = entry.get("license", "")
    if license_val and license_val not in ALLOWED_LICENSES:
        errors.append(f"Unapproved license: {license_val}. Allowed: {ALLOWED_LICENSES}")

    if entry.get("legal_review_status") != "APPROVED":
        errors.append(f"Legal review status is not APPROVED: {entry.get('legal_review_status')}")

    return len(errors) == 0, errors
