"""Positive license match. Silence is not compatibility, and a comment cannot waive GPL or NC."""

from legal.ledger.license_notice import conflicting_license_ids, detected_licenses

ALLOWED = frozenset({
    'CC-BY-SA-4.0', 'GFDL-1.3-only', 'CC0-1.0', 'PUBLIC-DOMAIN', 'CC-BY-2.0-FR',
})


def positive_match(notice, declared, co_offered=()):
    """True only when the notice names the declared license and every co-offer, with no conflict."""
    if declared not in ALLOWED:
        return False, ['license_not_in_ledger']
    detected = detected_licenses(notice or '')
    if declared not in detected:
        return False, ['declared_license_not_in_notice']
    missing = [item for item in (co_offered or []) if item not in detected]
    if missing:
        return False, ['co_offer_not_in_notice']
    conflicts = conflicting_license_ids(detected, declared, co_offered or ())
    if conflicts:
        return False, ['conflict:' + ','.join(sorted(conflicts))]
    return True, []


def source_is_compatible(source, notice):
    if not source.get('compatible'):
        return False, [source.get('blocked_reason') or 'source_blocked']
    return positive_match(notice, source.get('declared_license'), source.get('co_offered_licenses') or [])
