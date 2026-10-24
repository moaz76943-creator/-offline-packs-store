"""Strict automatic selection for low-risk PRs; all other scopes need the incumbent approval path."""
import re

AUTO_SHA = re.compile(r'[0-9a-f]{40}\Z')
AUTO_SAFE_DOCS = ('docs/',)
AUTO_DENIED_DOCS = ('docs/governance/', 'docs/merge_coordinator/', 'docs/security/', 'docs/release/', 'docs/CI_')

SEARCH_QA_PREFIXES = ('tools/gha_factory/search_qa/', 'tests/gha_factory/search_qa/')

def auto_safe_files(files):
    if not isinstance(files, list) or not 1 <= len(files) <= 5:
        return False
    search_qa_files = True
    for f in files:
        if not isinstance(f, dict) or f.get('status') not in ('added', 'modified'):
            return False
        if f.get('previous_filename') is not None:
            return False
        path = f.get('filename')
        if not isinstance(path, str) or '..' in path.split('/') or '\\' in path or path.startswith('/'):
            return False
        doc = path.startswith(AUTO_SAFE_DOCS) and path.endswith('.md') and not path.startswith(AUTO_DENIED_DOCS)
        new_test = path.startswith('tests/') and path.endswith('.py') and f.get('status') == 'added'
        scoped_qa = path.startswith(SEARCH_QA_PREFIXES) and path.endswith('.py')
        if not (doc or new_test or scoped_qa):
            return False
        if not scoped_qa:
            search_qa_files = False
    return not (any(f['filename'].startswith(SEARCH_QA_PREFIXES) for f in files) and
                not search_qa_files)

def required_checks(files):
    # The active main ruleset requires this single exact-head check.
    # Scoped search QA below retains its additional targeted evidence.
    checks = ('public-pr-merge-gate',)
    if all(f['filename'].startswith(SEARCH_QA_PREFIXES) for f in files):
        return checks + ('audit (0, 1)', 'Validate no fictitious licensed packs',
                         'admission public regression')
    return checks

def auto_eligible(pr, checks, reviews, files, message, main_sha):
    if not isinstance(pr, dict) or pr.get('state') != 'open' or pr.get('draft'):
        return False, 'not an open ready PR'
    head = (pr.get('head') or {}).get('sha')
    if not isinstance(head, str) or not AUTO_SHA.fullmatch(head):
        return False, 'missing exact head SHA'
    if ((pr.get('base') or {}).get('ref') != 'main' or
        (pr.get('base') or {}).get('sha') != main_sha or
        ((pr.get('head') or {}).get('repo') or {}).get('full_name') != 'moaz76943-creator/-offline-packs-store' or
        (pr.get('user') or {}).get('login') != 'moaz76943-creator'):
        return False, 'branch or author out of autonomous scope'
    if pr.get('mergeable') is not True or pr.get('mergeable_state') != 'clean':
        return False, 'not cleanly mergeable'
    if not auto_safe_files(files):
        return False, 'changes exceed low-risk documentation/new-test scope'
    if not isinstance(reviews, list) or any(not isinstance(v, dict) for v in reviews):
        return False, 'invalid review evidence'
    latest = {}
    for i, review in enumerate(reviews):
        login = (review.get('user') or {}).get('login')
        stamp = review.get('submitted_at')
        if not isinstance(login, str) or not login or not isinstance(stamp, str) or not stamp:
            return False, 'incomplete reviewer evidence'
        key = (stamp, i)
        if login not in latest or key > latest[login][0]:
            latest[login] = (key, review)
    if any(pair[1].get('state') == 'CHANGES_REQUESTED' for pair in latest.values()):
        return False, 'outstanding changes requested'
    runs = checks.get('check_runs', []) if isinstance(checks, dict) else []
    for wanted in required_checks(files):
        eligible = [c for c in runs if isinstance(c, dict) and c.get('name') == wanted
                    and c.get('head_sha') == head and (c.get('app') or {}).get('slug') == 'github-actions']
        newest = max(eligible, key=lambda c: c.get('id', 0), default=None)
        if not newest or newest.get('status') != 'completed' or newest.get('conclusion') != 'success':
            return False, 'exact-head '+wanted+' is not passing'
    return True, 'low-risk scope and exact-head checks validated'
