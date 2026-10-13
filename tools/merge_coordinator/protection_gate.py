"""Read-only, fail-closed proof of active main rules before automatic writes."""
import json
import os
import sys
from urllib.request import Request, urlopen

REPO = 'moaz76943-creator/-offline-packs-store'
REQUIRED = 'public-pr-merge-gate'


def allowed(branch, active_rules=None):
    if not isinstance(branch, dict) or branch.get('name') != 'main' or branch.get('protected') is not True:
        return False
    if active_rules is not None:
        if not isinstance(active_rules, list) or len(active_rules) >= 100:
            return False
        by_type = {}
        for rule in active_rules:
            if isinstance(rule, dict):
                by_type.setdefault(rule.get('type'), []).append(rule)
        checks_ok = any(
            (rule.get('parameters') or {}).get('strict_required_status_checks_policy') is True
            and REQUIRED in {x.get('context') for x in (rule.get('parameters') or {}).get('required_status_checks', []) if isinstance(x, dict)}
            for rule in by_type.get('required_status_checks', []))
        reviews_ok = any((rule.get('parameters') or {}).get('required_approving_review_count', 0) >= 1
                         for rule in by_type.get('pull_request', []))
        return checks_ok and reviews_ok and 'non_fast_forward' in by_type and 'deletion' in by_type
    checks = (branch.get('protection') or {}).get('required_status_checks') or {}
    contexts = set(checks.get('contexts') or [])
    contexts.update(c.get('context') for c in checks.get('checks') or [] if isinstance(c, dict))
    return checks.get('strict') is True and checks.get('enforcement_level') == 'everyone' and REQUIRED in contexts


def read_api(path, token):
    req = Request(f'https://api.github.com/repos/{REPO}/{path}', headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def run():
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('missing token')
    branch = read_api('branches/main', token)
    rules = read_api('rules/branches/main?per_page=100', token)
    ok = allowed(branch, rules)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
            f.write('allowed=' + ('true' if ok else 'false') + '\n')
    print('MAIN_EFFECTIVE_RULES=' + ('VERIFIED' if ok else 'BLOCKED_OR_UNVERIFIED'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f'PROTECTION_GATE_ERROR: {exc}', file=sys.stderr)
        raise SystemExit(2)
