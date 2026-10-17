"""Single-writer low-risk PR discovery, called only by the incumbent coordinator."""
import os
from auto_policy import auto_eligible

def run_auto(gh, main_sha):
    """One bounded low-risk automatic squash, with fresh evidence at write time."""
    queue = gh.page('/pulls?state=open&base=main', limit=300)
    if not isinstance(queue, list):
        raise ValueError('invalid live pull-request listing')
    pool = [p for p in queue if isinstance(p, dict) and p.get('state') == 'open'
            and not p.get('draft') and isinstance(p.get('number'), int)]
    print('AUTO_DISCOVERY_READY=' + str(len(pool)))
    for brief in sorted(pool, key=lambda p: p['number']):
        num = brief['number']
        head = (brief.get('head') or {}).get('sha')
        if not isinstance(head, str) or len(head) != 40:
            continue
        if gh.main_sha() != main_sha:
            print('HALT: main changed during discovery')
            return 0
        pr, checks, reviews, files, msg = gh.query_pr(num, head)
        ok, why = auto_eligible(pr, checks, reviews, files, msg, main_sha)
        if not ok or head != (pr.get('head') or {}).get('sha'):
            print(f'AUTO_SKIP #{num}: {why}')
            continue
        if gh.page(f'/pulls/{num}/comments', limit=300):
            print(f'AUTO_SKIP #{num}: inline review comments require human resolution')
            continue
        if os.getenv('INTEGRATOR_APPLY') != 'true':
            print(f'AUTO_DRY_RUN #{num} SHA={head}')
            continue
        if gh.main_sha() != main_sha:
            print('HALT: main moved before automatic squash')
            return 0
        # Check current protection again, in addition to the incumbent workflow preflight.
        from protection_gate import allowed
        if not allowed(gh.get('/branches/main'), gh.get('/rules/branches/main?per_page=100')):
            print('HALT: strict main protection no longer verified')
            return 0
        fresh, fc, fr, ff, fm = gh.query_pr(num, head)
        qualified, reason = auto_eligible(fresh, fc, fr, ff, fm, main_sha)
        if not qualified or gh.page(f'/pulls/{num}/comments', limit=300):
            print(f'HALT: candidate changed or review started #{num}: {reason}')
            return 0
        if gh.main_sha() != main_sha:
            print('HALT: main moved immediately before squash')
            return 0
        result = gh.squash(num, head)
        if result.get('merged') is not True:
            raise ValueError('GitHub did not confirm automatic squash')
        print(f'AUTO_MERGED #{num} SHA={result.get("sha")}')
        return 0
    print('AUTO_NO_QUALIFIED_MERGE: no safe code or review bypass')
    return 0
