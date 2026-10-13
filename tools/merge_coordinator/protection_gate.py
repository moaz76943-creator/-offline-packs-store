"""Fail-closed proof of protected main before any scheduled write transaction."""
import json
import os
import sys
from urllib.request import Request, urlopen

REPO = 'moaz76943-creator/-offline-packs-store'
REQUIRED = 'public-pr-merge-gate'


def allowed(branch):
    if not isinstance(branch, dict) or branch.get('name') != 'main' or branch.get('protected') is not True:
        return False
    checks = (branch.get('protection') or {}).get('required_status_checks') or {}
    contexts = set(checks.get('contexts') or [])
    contexts.update(c.get('context') for c in checks.get('checks') or [] if isinstance(c, dict))
    return checks.get('strict') is True and checks.get('enforcement_level') == 'everyone' and REQUIRED in contexts


def run():
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('missing token')
    req = Request(f'https://api.github.com/repos/{REPO}/branches/main', headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    with urlopen(req, timeout=15) as response:
        branch = json.load(response)
    ok = allowed(branch)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
            f.write('allowed=' + ('true' if ok else 'false') + '\n')
    print('PROTECTED_MAIN_AND_STRICT_CHECKS=' + ('PASS' if ok else 'BLOCKED_OR_UNVERIFIED'))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f'PROTECTION_GATE_ERROR: {exc}', file=sys.stderr)
        raise SystemExit(2)
