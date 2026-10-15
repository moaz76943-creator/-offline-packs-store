"""Conservative license preflight on sources verified against legal/ledger.

COMPATIBLE denotes *only* license shape + recorded rights evidence, not legal
clearance; source and release gates remain mandatory.
"""
from legal.ledger.admission import LICENSES, OBLIGATIONS
from tools.contribution_gate.evidence import load_verified_ledger, exact_source_reference

def check_compatibility(source_refs, output_license, is_derivative=True, *, repo_root=None):
    base = {"status": "REVIEW_REQUIRED", "reason": "", "obligations": set(),
            "publication_approved": False}
    if output_license not in LICENSES:
        return {**base, "reason": "unsupported output license"}
    if not isinstance(source_refs, list) or not source_refs:
        return {**base, "reason": "missing source evidence"}
    try:
        verified_sources_dict = load_verified_ledger(repo_root)
        sources = [exact_source_reference(ref, verified_sources_dict) for ref in source_refs]
    except (ValueError, TypeError, OSError) as exc:
        return {**base, "reason": str(exc)}
    ids = [s["license"]["id"] for s in sources]
    obligations = set().union(*(set(OBLIGATIONS.get(lid, ())) for lid in ids))
    copyleft = set(ids).intersection(OBLIGATIONS)
    if output_license == "PUBLIC-DOMAIN" and any(lid != "PUBLIC-DOMAIN" for lid in ids):
        return {**base, "status": "INCOMPATIBLE",
                "reason": "public domain is not a blanket relicensing claim"}
    if is_derivative:
        if len(copyleft) > 1:
            return {**base, "status": "INCOMPATIBLE",
                    "reason": "GFDL and CC BY-SA derivative conflict"}
        if copyleft and output_license not in copyleft:
            return {**base, "status": "INCOMPATIBLE", "reason": "copyleft relicensing conflict"}
    elif copyleft:
        # The collection and its separate component licenses cannot be conflated.
        return {**base, "reason": "aggregation requires independent collection license review",
                "obligations": obligations}
    return {**base, "status": "COMPATIBLE", "reason": "evidence preflight only",
            "obligations": obligations}
