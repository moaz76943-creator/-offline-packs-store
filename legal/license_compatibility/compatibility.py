"""Conservative license preflight on sources verified against legal/ledger.

COMPATIBLE denotes *only* license shape + recorded rights evidence, not legal
clearance; source and release gates remain mandatory.
"""
from legal.ledger.admission import LICENSES, OBLIGATIONS
from tools.contribution_gate.evidence import verified_sources

def check_compatibility(sources, output_license, is_derivative=True, *, repo_root=None):
    """
    Evaluates source-aware redistribution compatibility against the canonical legal ledger.
    Implements explicit policy rules to distinguish data aggregation from derivative transformations,
    tracks independent obligations, and enforces that incompatible combinations fail closed.
    """
    # 8. Implement a compatibility-decision API with reason codes.
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

    # 6. Mark unsupported license combinations as reviewRequired.
    if output_license not in LICENSES:
        return {**base, "reason": "unsupported output license"}

    # 7. Fail closed when source provenance is unknown.
    if not isinstance(sources, list) or not sources:
        return {**base, "reason": "missing source evidence"}

    # 1. Load source license identities from the canonical ledger.
    # 9. Validate combinations for multiple source records.
    try:
        verified_sources({"schema_version": "1.0.0", "sources": sources}, repo_root)
    except (ValueError, TypeError, OSError) as exc:
        return {**base, "reason": str(exc)}

    # Extract all license IDs from the provided, verified sources
    ids = [s["license"]["id"] for s in sources]

    # Gather raw obligations based on known license families
    raw_obligations = set().union(*(set(OBLIGATIONS.get(lid, ())) for lid in ids))

    # 4. Track share-alike, attribution, modification and redistribution obligations separately.
    obligations = {
        "share_alike": "sharealike" in raw_obligations or "GFDL-1.3-only" in ids,
        "attribution": "attribution" in raw_obligations or "copyright_notices" in raw_obligations,
        "modification": "changes_disclosed" in raw_obligations or "history" in raw_obligations,
        # A public-domain source adds no obligation and must not cancel one.
        "redistribution": any(lid in LICENSES and lid != "PUBLIC-DOMAIN" for lid in ids)
    }

    base["obligations"] = obligations

    # Find which source licenses impose obligations
    with_obligations = set(ids).intersection(OBLIGATIONS)
    # Determine copyleft licenses by looking for sharealike or history
    copyleft = {lid for lid in with_obligations if "sharealike" in OBLIGATIONS.get(lid, ()) or "history" in OBLIGATIONS.get(lid, ())}

    # 2. Implement explicit policy rules for known license families.
    if output_license in ("PUBLIC-DOMAIN", "CC0-1.0") and with_obligations:
        return {**base, "status": "INCOMPATIBLE",
                "reason": f"cannot drop obligations for {output_license}"}

    if output_license == "PUBLIC-DOMAIN" and any(lid != "PUBLIC-DOMAIN" for lid in ids):
        return {**base, "status": "INCOMPATIBLE",
                "reason": "public domain is not a blanket relicensing claim"}

    # 3. Distinguish data aggregation from derivative transformations.
    if is_derivative:
        # 5. Do not treat CC BY-SA and GFDL as universally compatible.
        if len(copyleft) > 1:
            return {**base, "status": "INCOMPATIBLE",
                    "reason": "GFDL and CC BY-SA derivative conflict"}
        if copyleft and output_license not in copyleft:
            return {**base, "status": "INCOMPATIBLE", "reason": "copyleft relicensing conflict"}
    elif copyleft:
        # The collection and its separate component licenses cannot be conflated.
        return {**base, "reason": "aggregation requires independent collection license review"}

    # This helper cannot approve a conversion that the enforced admission
    # gate forbids. Retain original terms until independent legal review.
    if 'CC-BY-2.0-FR' in ids and output_license != 'CC-BY-2.0-FR':
        return {**base, "reason": "license conversion requires independent review"}

    # 12. Produce an admission decision consumable by J094.
    return {**base, "status": "COMPATIBLE", "reason": "evidence preflight only"}
