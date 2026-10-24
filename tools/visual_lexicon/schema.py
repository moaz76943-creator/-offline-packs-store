import re

PATH_REGEX = re.compile(r'^[MmLlHhVvCcSsQqTtAaZz0-9\s.,-]+$')
HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$')

def validate_token(token):
    if not isinstance(token, dict):
        raise ValueError("Token must be a dictionary")

    required_keys = {'concept_id', 'version', 'viewBox', 'paths', 'palette', 'semantic_label', 'alt_text'}
    if not required_keys.issubset(token.keys()):
        missing = required_keys - token.keys()
        raise ValueError(f"Missing required token keys: {missing}")

    if not isinstance(token['concept_id'], str) or not token['concept_id']:
        raise ValueError("concept_id must be a non-empty string")

    if not isinstance(token['version'], int) or token['version'] < 1:
        raise ValueError("version must be a positive integer")

    view_box = token['viewBox']
    if not isinstance(view_box, list) or len(view_box) != 4 or not all(isinstance(x, (int, float)) for x in view_box):
        raise ValueError("viewBox must be a list of 4 numbers")

    paths = token['paths']
    if not isinstance(paths, list) or not paths:
        raise ValueError("paths must be a non-empty list")

    if len(paths) > 50:
        raise ValueError("Maximum of 50 paths allowed per token")

    for p in paths:
        if not isinstance(p, str):
            raise ValueError("each path must be a string")
        if not PATH_REGEX.fullmatch(p):
            raise ValueError("Path contains invalid or potentially unsafe characters")

    palette = token['palette']
    if not isinstance(palette, list):
        raise ValueError("palette must be a list of hex color strings")
    for c in palette:
        if not isinstance(c, str) or not HEX_COLOR.fullmatch(c):
            raise ValueError("invalid hex color in palette")

    semantic_label = token['semantic_label']
    if not isinstance(semantic_label, str) or not semantic_label or len(semantic_label) > 100:
        raise ValueError("semantic_label must be a string up to 100 characters")

    alt_text = token['alt_text']
    if not isinstance(alt_text, str) or not alt_text or len(alt_text) > 200:
        raise ValueError("alt_text must be a string up to 200 characters")

    return True

def validate_manifest(manifest):
    """Manifests for verified CC0 fixtures."""
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a dictionary")

    required_keys = {'concept_id', 'author', 'license', 'source'}
    if not required_keys.issubset(manifest.keys()):
        missing = required_keys - manifest.keys()
        raise ValueError(f"Missing required manifest keys: {missing}")

    if manifest.get('license') != 'CC0-1.0':
        raise ValueError("license must be 'CC0-1.0'")

    for key in required_keys:
        if not isinstance(manifest[key], str) or not manifest[key]:
            raise ValueError(f"Manifest key {key} must be a non-empty string")

    return True
