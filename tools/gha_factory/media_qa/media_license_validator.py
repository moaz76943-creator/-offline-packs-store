from typing import Dict, Any, List, Tuple

ALLOWED_MEDIA_LICENSES = {
    "CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "Public Domain", "MIT"
}

ALLOWED_AUDIO_MIMES = {
    "audio/ogg", "audio/mpeg", "audio/wav", "audio/mp4"
}

ALLOWED_IMAGE_MIMES = {
    "image/png", "image/jpeg", "image/webp", "image/svg+xml"
}

MAX_MEDIA_FILE_BYTES = 2 * 1024 * 1024  # 2MB max per asset to avoid memory bloat

def validate_media_metadata(entry: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates open license compliance, supported MIME types, and size constraints (<= 2MB)
    for audio pronunciation clips and image assets.
    """
    errors = []
    lic = str(entry.get("license", "")).strip()
    if not lic or lic not in ALLOWED_MEDIA_LICENSES:
        errors.append(f"Unapproved or missing media license: '{lic}'. Allowed: {ALLOWED_MEDIA_LICENSES}")

    mime = str(entry.get("mime_type", "")).strip().lower()
    allowed_mimes = ALLOWED_AUDIO_MIMES.union(ALLOWED_IMAGE_MIMES)
    if not mime or mime not in allowed_mimes:
        errors.append(f"Unsupported MIME type: '{mime}'. Allowed: audio (ogg/mp3/wav) and image (png/jpg/webp/svg)")

    size = entry.get("size_bytes", 0)
    if not isinstance(size, int) or size <= 0:
        errors.append(f"Invalid media size: {size}")
    elif size > MAX_MEDIA_FILE_BYTES:
        errors.append(f"Media file size ({size} bytes) exceeds maximum bound of 2MB")

    return len(errors) == 0, errors
