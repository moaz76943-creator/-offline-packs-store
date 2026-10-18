"""Decide whether the rolling candidate PR may be squash-merged. The caller performs the API call."""


def merge_decision(checks, unresolved_threads, halt=False):
    """Merge only when required checks passed and no review thread is still open."""
    if halt:
        return False, 'kill switch is on'
    if unresolved_threads:
        return False, 'unresolved review'
    if not checks:
        return False, 'no checks'
    pending = [item.get('name') for item in checks if item.get('status') != 'completed']
    if pending:
        return False, 'checks still running'
    failed = [
        item.get('name') for item in checks
        if item.get('conclusion') not in ('success', 'skipped')
    ]
    if failed:
        return False, 'checks failed: ' + ', '.join(str(name) for name in failed)
    gate = any(
        item.get('name') == 'public-pr-merge-gate' and item.get('conclusion') == 'success'
        for item in checks
    )
    if not gate:
        return False, 'public-pr-merge-gate has not passed'
    return True, 'checks are green and no review thread is open'
