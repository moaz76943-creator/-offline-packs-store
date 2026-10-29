from typing import Dict, Any, List, Tuple

ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-SA-3.0", "MIT", "Apache-2.0"}

def validate_manifest_structure(manifest: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = []
    if not isinstance(manifest, dict):
        return False, ["Manifest root must be a JSON object"]

    packs = manifest.get("packs")
    if not isinstance(packs, list):
        return False, ["Manifest must contain a 'packs' list"]

    if len(packs) == 0:
        return False, ["Manifest 'packs' list cannot be empty"]

    for idx, pack in enumerate(packs):
        pack_id = pack.get("pack_id", f"index_{idx}")

        for req in ["pack_id", "filename", "sha256", "size_bytes", "license"]:
            if req not in pack or not pack[req]:
                errors.append(f"Pack '{pack_id}' missing or empty field: '{req}'")

        sha = pack.get("sha256", "")
        if sha and len(sha) != 64:
            errors.append(f"Pack '{pack_id}' has invalid SHA-256 length ({len(sha)} chars)")

        lic = pack.get("license", "")
        if lic and lic not in ALLOWED_LICENSES:
            errors.append(f"Pack '{pack_id}' has unapproved license: '{lic}'")

        size = pack.get("size_bytes", 0)
        if isinstance(size, int) and size <= 0:
            errors.append(f"Pack '{pack_id}' has non-positive size_bytes: {size}")

    return len(errors) == 0, errors
