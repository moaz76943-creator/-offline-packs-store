import json

def validate_manifest(manifest: dict) -> bool:
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a dictionary.")

    required_keys = {"concept_id", "author", "source", "license"}
    missing_keys = required_keys - set(manifest.keys())

    if missing_keys:
        raise ValueError(f"Manifest missing required fields: {missing_keys}")

    for key in required_keys:
        if not manifest[key] or not isinstance(manifest[key], str):
             raise ValueError(f"Field {key} must be a non-empty string.")

    # Enforce recognized open licenses (e.g. CC0, Public Domain)
    allowed_licenses = {"CC0", "CC0-1.0", "Public Domain"}
    if manifest["license"] not in allowed_licenses:
        raise ValueError(f"Unlicensed or unsupported license: {manifest['license']}. Must be explicitly authorized.")

    return True

def generate_incremental_update(old_manifests: dict, new_manifests: dict) -> dict:
    """
    Computes an incremental update between two dictionaries of manifests.
    Maps concept_id to manifest dictionary.
    Returns a dictionary of added, updated, deleted, unchanged lists of concept_ids.
    """
    added = []
    updated = []
    deleted = []
    unchanged = []

    for concept_id, new_manifest in new_manifests.items():
        if concept_id not in old_manifests:
            added.append(concept_id)
        else:
            old_manifest = old_manifests[concept_id]
            # Simple dictionary comparison
            if json.dumps(old_manifest, sort_keys=True) != json.dumps(new_manifest, sort_keys=True):
                updated.append(concept_id)
            else:
                unchanged.append(concept_id)

    for concept_id in old_manifests:
        if concept_id not in new_manifests:
            deleted.append(concept_id)

    return {
        "added": added,
        "updated": updated,
        "deleted": deleted,
        "unchanged": unchanged
    }
