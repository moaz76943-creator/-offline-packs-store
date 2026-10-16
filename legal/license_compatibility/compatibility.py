"""Conservative license preflight on sources verified against legal/ledger.

COMPATIBLE denotes *only* license shape + recorded rights evidence, not legal
clearance; source and release gates remain mandatory.
"""
from legal.ledger.admission import LICENSES, OBLIGATIONS
from tools.contribution_gate.evidence import verified_sources

def check_compatibility(sources, output_license, is_derivative=True, *, repo_root=None):
    base = {
        "status": "REVIEW_REQUIRED",
        "reason": "",
        "obligations": {"share_alike": False, "attribution": False,
                        "modification": False, "redistribution": False},
        "publication_approved": False
    }
    if output_license not in LICENSES:
        return {**base, "reason": "unsupported output license"}
    if not isinstance(sources, list) or not sources:
        return {**base, "reason": "missing source evidence"}
    try:
        verified_sources({"schema_version": "1.0.0", "sources": sources}, repo_root)
    except (ValueError, TypeError, OSError) as exc:
        return {**base, "reason": str(exc)}
    ids = [s["license"]["id"] for s in sources]

    unsupported_sources = [lid for lid in ids if lid not in LICENSES]
    if unsupported_sources:
        return {**base, "reason": f"unsupported source licenses: {', '.join(set(unsupported_sources))}"}

    raw_obligations = set().union(*(set(OBLIGATIONS.get(lid, ())) for lid in ids))
    categorized_obligations = {
        "share_alike": bool(raw_obligations.intersection({'sharealike', 'transparent_copy_checked'})),
        "attribution": bool(raw_obligations.intersection({'attribution', 'copyright_notices'})),
        "modification": bool(raw_obligations.intersection({'changes_disclosed', 'history'})),
        "redistribution": bool(raw_obligations.intersection({'license_link', 'license_copy', 'no_additional_restrictions', 'invariant_sections_checked', 'cover_texts_checked'}))
    }

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
                "obligations": categorized_obligations}
    return {**base, "status": "COMPATIBLE", "reason": "evidence preflight only",
            "obligations": categorized_obligations}
