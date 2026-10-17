"""Shared negative-only license-notice scan for the ledger and factory gates.

Recognizing a SPDX-style identifier never grants redistribution rights.
Both gates import this module so their conflict rules cannot drift apart.
"""
import re
from pathlib import Path

MAX_LICENSE_NOTICE_BYTES = 1024 * 1024

# (license id, normalized token, unversioned)
# Unversioned tokens do not match when the next hyphen-segment is a version
# number, so "CC-BY-SA 3.0" is not silently relabeled as CC-BY-SA-4.0.
_MARKERS = (
    ('CC0-1.0', 'cc0-1-0', False),
    ('CC-BY-SA-4.0', 'cc-by-sa-4-0', False),
    ('CC-BY-SA-4.0', 'attribution-sharealike-4-0', False),
    ('CC-BY-SA-4.0', 'cc-by-sa', True),
    ('GFDL-1.3-only', 'gfdl-1-3', False),
    ('GFDL-1.3-only', 'gnu-free-documentation-license-version-1-3', False),
    ('GFDL-1.3-only', 'gnu-free-documentation-license-1-3', False),
    ('GFDL-1.3-only', 'gfdl', True),
    ('CC-BY-NC-SA-4.0', 'cc-by-nc-sa-4-0', False),
    ('CC-BY-NC-SA-4.0', 'attribution-noncommercial-sharealike-4-0', False),
    ('CC-BY-NC-4.0', 'cc-by-nc-4-0', False),
    ('CC-BY-NC-4.0', 'cc-by-nc', True),
    ('CC-BY-NC-ND-4.0', 'cc-by-nc-nd-4-0', False),
    ('CC-BY-ND-4.0', 'cc-by-nd-4-0', False),
    ('CC-BY-ND-4.0', 'cc-by-nd', True),
    ('ALL-RIGHTS-RESERVED', 'all-rights-reserved', False),
)

ALWAYS_CONFLICT = frozenset({
    'CC-BY-NC-SA-4.0', 'CC-BY-NC-4.0', 'CC-BY-NC-ND-4.0', 'CC-BY-ND-4.0',
    'ALL-RIGHTS-RESERVED',
})
CO_OFFERABLE = frozenset({'CC-BY-SA-4.0', 'GFDL-1.3-only', 'CC0-1.0', 'PUBLIC-DOMAIN'})


def normalize_notice(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def _has_marker(normalized, token, unversioned):
    start = 0
    while True:
        index = normalized.find(token, start)
        if index < 0:
            return False
        end = index + len(token)
        before_ok = index == 0 or normalized[index - 1] == '-'
        after = normalized[end:end + 1]
        if before_ok and after in ('', '-'):
            if not unversioned or after != '-':
                return True
            version = normalized[end + 1:].split('-', 1)[0]
            if not version.isdigit():
                return True
        start = index + 1


def detected_licenses(text):
    if not isinstance(text, str):
        return frozenset()
    normalized = normalize_notice(text)
    found = set()
    for license_id, token, unversioned in _MARKERS:
        if _has_marker(normalized, token, unversioned):
            found.add(license_id)
    return frozenset(found)


def read_notice(path):
    """Return notice text, or None when it cannot be checked safely."""
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_LICENSE_NOTICE_BYTES + 1)
        if len(raw) > MAX_LICENSE_NOTICE_BYTES:
            return None
        return raw.decode('utf-8')
    except (OSError, UnicodeError):
        return None


def allowed_license_set(declared_license, co_offered=()):
    """Return the ids a notice may name, or None when the metadata is invalid."""
    if not isinstance(declared_license, str) or not declared_license:
        return None
    if co_offered is None:
        co_offered = ()
    if isinstance(co_offered, (str, bytes)) or not isinstance(co_offered, (list, tuple)):
        return None
    allowed = {declared_license}
    for item in co_offered:
        if item == declared_license:
            continue
        if item not in CO_OFFERABLE or item in ALWAYS_CONFLICT:
            return None
        allowed.add(item)
    return frozenset(allowed)


def conflicting_license_ids(detected, declared_license, co_offered=()):
    allowed = allowed_license_set(declared_license, co_offered)
    if allowed is None:
        return frozenset({'INVALID'})
    present = set(detected)
    if declared_license == 'CC0-1.0':
        # CC0 is a public-domain dedication. The reverse (declared
        # PUBLIC-DOMAIN plus a CC0 identifier) stays a conflict.
        present.discard('PUBLIC-DOMAIN')
    return frozenset(
        name for name in present if name in ALWAYS_CONFLICT or name not in allowed
    )


def license_notice_conflicts(path, declared_license, co_offered=()):
    """Reject explicit incompatible notices; never infer legal approval."""
    notice = read_notice(path)
    if notice is None:
        return True
    return bool(conflicting_license_ids(
        detected_licenses(notice), declared_license, co_offered))
