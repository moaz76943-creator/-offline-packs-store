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
        "obligations": {
            "share_alike": False,
            "attribution": False,
            "modification": False,
            "redistribution": False
        },
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

    raw_obligations = set().union(*(set(OBLIGATIONS.get(lid, ())) for lid in ids))

    obligations = {
        "share_alike": "sharealike" in raw_obligations or "GFDL-1.3-only" in ids,
        "attribution": "attribution" in raw_obligations or "copyright_notices" in raw_obligations,
        "modification": "changes_disclosed" in raw_obligations or "history" in raw_obligations,
        # A public-domain source adds no obligation and must not cancel one.
        "redistribution": any(lid in LICENSES and lid != "PUBLIC-DOMAIN" for lid in ids)
    }

    base["obligations"] = obligations

    copyleft = set(ids).intersection({"CC-BY-SA-4.0", "GFDL-1.3-only"})
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
        return {**base, "reason": "aggregation requires independent collection license review"}
    return {**base, "status": "COMPATIBLE", "reason": "evidence preflight only"}
