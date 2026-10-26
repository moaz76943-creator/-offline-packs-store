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
    ('CC0-1.0', 'cc0-license', False),
    ('CC0-1.0', 'creative-commons-cc0', False),
    ('CC0-1.0', 'creative-commons-zero', False),
    ('CC0-1.0', 'publicdomain-zero-1-0', False),
    ('PUBLIC-DOMAIN', 'public-domain', False),
    ('CC-BY-SA-4.0', 'cc-by-sa-4-0', False),
    ('CC-BY-SA-4.0', 'attribution-sharealike-4-0', False),
    ('CC-BY-SA-4.0', 'cc-by-sa', True),
    # French 2.0 Attribution port. Not share-alike, and not a match for CC-BY-SA.
    ('CC-BY-2.0-FR', 'cc-by-2-0-fr', False),
    ('CC-BY-2.0-FR', 'creative-commons-attribution-2-0-france', False),
    ('CC-BY-2.0-FR', 'attribution-2-0-france', False),
    ('GFDL-1.3-only', 'gfdl-1-3', False),
    ('GFDL-1.3-only', 'gnu-free-documentation-license-version-1-3', False),
    ('GFDL-1.3-only', 'gnu-free-documentation-license-1-3', False),
    ('GFDL-1.3-only', 'gfdl', True),
    ('CC-BY-NC-SA-4.0', 'cc-by-nc-sa-4-0', False),
    ('CC-BY-NC-SA-4.0', 'attribution-noncommercial-sharealike-4-0', False),
    ('CC-BY-NC-ND-4.0', 'attribution-noncommercial-noderivatives-4-0', False),
    ('CC-BY-NC-ND-4.0', 'attribution-noncommercial-noderivatives', True),
    ('CC-BY-NC-4.0', 'cc-by-nc-4-0', False),
    ('CC-BY-NC-4.0', 'cc-by-nc', True),
    ('CC-BY-NC-4.0', 'attribution-noncommercial-4-0', False),
    ('CC-BY-NC-4.0', 'attribution-noncommercial', True),
    ('CC-BY-NC-ND-4.0', 'cc-by-nc-nd-4-0', False),
    ('CC-BY-ND-4.0', 'cc-by-nd-4-0', False),
    ('CC-BY-ND-4.0', 'cc-by-nd', True),
    ('CC-BY-ND-4.0', 'attribution-noderivatives-4-0', False),
    ('CC-BY-ND-4.0', 'attribution-noderivatives', True),
    ('ALL-RIGHTS-RESERVED', 'all-rights-reserved', False),
)

ALWAYS_CONFLICT = frozenset({
    'CC-BY-NC-SA-4.0', 'CC-BY-NC-4.0', 'CC-BY-NC-ND-4.0', 'CC-BY-ND-4.0',
    'ALL-RIGHTS-RESERVED',
})
CO_OFFERABLE = frozenset({'CC-BY-SA-4.0', 'GFDL-1.3-only', 'CC0-1.0', 'PUBLIC-DOMAIN'})
# Longer tokens first. A numeric suffix that no known marker records becomes
# its own id (CC-BY-NC-3.0). Do not scan bare "attribution-sharealike": the
# Wikidata copyright page names Attribution-ShareAlike 3.0 beside CC0.
_VERSIONED_FAMILIES = (
    ('CC-BY-NC-SA', 'attribution-noncommercial-sharealike'),
    ('CC-BY-NC-ND', 'attribution-noncommercial-noderivatives'),
    ('CC-BY-NC', 'attribution-noncommercial'),
    ('CC-BY-ND', 'attribution-noderivatives'),
    ('CC-BY-NC-SA', 'cc-by-nc-sa'),
    ('CC-BY-NC-ND', 'cc-by-nc-nd'),
    ('CC-BY-NC', 'cc-by-nc'),
    ('CC-BY-ND', 'cc-by-nd'),
    ('CC-BY-SA', 'cc-by-sa'),
    ('GFDL', 'gfdl'),
)


def is_unconditional_conflict(license_id):
    """NC and ND conflict at every version, including ones the schema does not list."""
    if not isinstance(license_id, str):
        return False
    if license_id in ALWAYS_CONFLICT:
        return True
    return license_id.startswith('CC-BY-NC') or license_id.startswith('CC-BY-ND')


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


def _dotted_version(normalized, end):
    """Return a dotted numeric suffix immediately after a family token, if any."""
    if end >= len(normalized) or normalized[end] != '-':
        return None
    parts = []
    for segment in normalized[end + 1:].split('-'):
        if not segment.isdigit():
            break
        parts.append(segment)
    if not parts:
        return None
    return '.'.join(parts)


def _unrecognized_version_ids(normalized, already):
    """Record CC-BY-NC-3.0-style ids when a known marker does not already cover them."""
    extra = set()
    for family, token in _VERSIONED_FAMILIES:
        start = 0
        while True:
            index = normalized.find(token, start)
            if index < 0:
                break
            end = index + len(token)
            before_ok = index == 0 or normalized[index - 1] == '-'
            if before_ok:
                version = _dotted_version(normalized, end)
                if version:
                    license_id = f'{family}-{version}'
                    covered = license_id in already or any(
                        existing.startswith(f'{family}-{version}') for existing in already
                    )
                    if not covered:
                        extra.add(license_id)
            start = index + 1
    return extra


def detected_licenses(text):
    if not isinstance(text, str):
        return frozenset()
    normalized = normalize_notice(text)
    found = set()
    for license_id, token, unversioned in _MARKERS:
        if _has_marker(normalized, token, unversioned):
            found.add(license_id)
    found |= _unrecognized_version_ids(normalized, found)
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
        if item not in CO_OFFERABLE or is_unconditional_conflict(item):
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
        name for name in present
        if is_unconditional_conflict(name) or name not in allowed
    )


def incidental_public_domain(text):
    """True when public-domain wording is not a dedication of this work.

    Eligibility phrases ("in the public domain", "entered the public domain")
    and a Wiktionary page title for public-domain sources are not a dedication.
    "This work is in the public domain" and "dedicated ... to the public domain"
    stay real PUBLIC-DOMAIN claims.
    """
    if not isinstance(text, str):
        return False
    normalized = normalize_notice(text)
    token = 'public-domain'
    if token not in normalized:
        return False
    start = 0
    found = False
    while True:
        index = normalized.find(token, start)
        if index < 0:
            break
        found = True
        prefix = normalized[max(0, index - 48):index]
        if 'dedicat' in prefix or prefix.endswith('work-is-in-the-'):
            return False
        short = normalized[max(0, index - 110):index]
        suffix = normalized[index + len(token):index + len(token) + 16]
        # Explicit claims about this dataset, its sentences or its material are
        # NOT eligibility language. Exempt only identifiable third-party
        # examples/conditional language and the Wiktionary source-page title.
        eligibility = any(short.endswith(phrase) for phrase in (
            'because-the-material-is-in-the-',
            'meaning-that-it-is-in-the-',
            'if-the-material-is-in-the-',
            'if-it-is-in-the-',
            'if-that-content-has-entered-the-',
        ))
        source_page = short.endswith('wiktionary-') and suffix.startswith('-sources')
        if not (eligibility or source_page):
            return False
        start = index + len(token)
    return found


def license_notice_conflicts(path, declared_license, co_offered=()):
    """Reject explicit incompatible notices; never infer legal approval."""
    notice = read_notice(path)
    if notice is None:
        return True
    detected = set(detected_licenses(notice))
    if declared_license != 'PUBLIC-DOMAIN' and incidental_public_domain(notice):
        detected.discard('PUBLIC-DOMAIN')
    return bool(conflicting_license_ids(detected, declared_license, co_offered))
