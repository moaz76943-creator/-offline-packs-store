"""Strict automatic selection for low-risk PRs; all other scopes need the incumbent approval path."""
import re

AUTO_SHA = re.compile(r'[0-9a-f]{40}\Z')
AUTO_SAFE_DOCS = ('docs/',)
AUTO_DENIED_DOCS = ('docs/governance/', 'docs/merge_coordinator/', 'docs/security/', 'docs/release/', 'docs/CI_')

def auto_safe_files(files):
    if not isinstance(files, list) or not 1 <= len(files) <= 5:
        return False
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
        if not (doc or new_test):
            return False
    return True

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
    if re.search(r'\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\]|^skip-checks\s*:\s*true\s*$', message, re.I | re.M):
        return False, 'CI-skipping commit'
    if not isinstance(reviews, list) or any(
        not isinstance(v, dict) or v.get('state') in ('CHANGES_REQUESTED', 'DISMISSED') for v in reviews
    ):
        return False, 'blocking or invalid reviews'
    runs = checks.get('check_runs', []) if isinstance(checks, dict) else []
    for wanted in ('public-pr-merge-gate', 'validate'):
        eligible = [c for c in runs if isinstance(c, dict) and c.get('name') == wanted
                    and c.get('head_sha') == head and (c.get('app') or {}).get('slug') == 'github-actions']
        newest = max(eligible, key=lambda c: c.get('id', 0), default=None)
        if not newest or newest.get('status') != 'completed' or newest.get('conclusion') != 'success':
            return False, 'exact-head '+wanted+' is not passing'
    return True, 'low-risk scope and exact-head checks validated'
