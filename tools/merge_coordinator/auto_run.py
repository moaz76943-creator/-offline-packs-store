"""Single-writer low-risk PR discovery, called only by the incumbent coordinator."""
import os
from auto_policy import auto_eligible

REVIEW_THREADS_QUERY = '''query($cursor:String, $number:Int!) {
 repository(owner:"moaz76943-creator",name:"-offline-packs-store") {
  pullRequest(number:$number) {
   reviewThreads(first:100,after:$cursor) {
    nodes { isResolved }
    pageInfo { hasNextPage endCursor }
   }
  }
 }
}'''

def has_unresolved_threads(gh, number):
    """Ignore resolved historical feedback; require a real review-thread response."""
    cursor = None
    for _ in range(5):
        result = gh.request('/graphql', method='POST', data={
            'query': REVIEW_THREADS_QUERY, 'variables': {'number': number, 'cursor': cursor}})
        if not isinstance(result, dict) or result.get('errors'):
            raise ValueError('review thread GraphQL evidence unavailable')
        try:
            group = result['data']['repository']['pullRequest']['reviewThreads']
            nodes, page = group['nodes'], group['pageInfo']
            if not isinstance(nodes, list) or not isinstance(page['hasNextPage'], bool):
                raise ValueError('malformed review thread evidence')
            if any(not isinstance(item, dict) or item.get('isResolved') is not True for item in nodes):
                return True
            if not page['hasNextPage']:
                return False
            new_cursor = page['endCursor']
            if not isinstance(new_cursor, str) or not new_cursor or new_cursor == cursor:
                raise ValueError('review pagination cursor missing or unchanged')
            cursor = new_cursor
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError('incomplete review thread evidence') from exc
    raise ValueError('review thread pagination exceeded bounded limit')

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
        if has_unresolved_threads(gh, num):
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
        if not qualified or has_unresolved_threads(gh, num):
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
