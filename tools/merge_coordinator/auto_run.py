"""Single-writer low-risk PR discovery, called only by the incumbent coordinator."""
import os
import urllib.error
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
    """Merge up to eight independent, low-risk and freshly checked PRs.

    Refresh the canonical main, pull list, and all exact-SHA evidence after
    each successful integration. All other changes stay with the existing
    explicit authorization path.
    """
    merged_count = 0
    merged_numbers = set()  # Do not reprocess an already confirmed merge if REST lists lag.
    for _ in range(8):
        if gh.main_sha() != main_sha:
            print('HALT: main changed outside this batch')
            return 0
        queue = gh.page('/pulls?state=open&base=main', limit=300)
        if not isinstance(queue, list):
            raise ValueError('invalid live pull-request listing')
        pool = [p for p in queue if isinstance(p, dict) and
                p.get('state') == 'open' and not p.get('draft') and
                isinstance(p.get('number'), int) and
                p['number'] not in merged_numbers]
        # GitHub may report a historical base.sha on an otherwise current PR.
        # Treat it as a hint, not a veto: the fresh PR, exact-head checks and
        # protected-main rules are verified again before any squash.
        current = [p for p in pool if (p.get('base') or {}).get('ref') == 'main']
        stale = sum((p.get('base') or {}).get('sha') != main_sha for p in current)
        print(f'AUTO_DISCOVERY_READY={len(pool)}')
        print(f'AUTO_STALE_BASE_HINTS={stale}')
        print(f'AUTO_CURRENT_BASE_CANDIDATES={len(current)}')
        merged_this_step = False
        for brief in sorted(current, key=lambda p: p['number'], reverse=True):
            num = brief['number']
            head = (brief.get('head') or {}).get('sha')
            if not isinstance(head, str) or len(head) != 40:
                continue
            if gh.main_sha() != main_sha:
                print('HALT: main moved during discovery')
                return 0
            pr, checks, reviews, files, msg = gh.query_pr(num, head)
            ok, why = auto_eligible(pr, checks, reviews, files, msg, main_sha)
            if not ok or head != (pr.get('head') or {}).get('sha'):
                print(f'AUTO_SKIP #{num}: {why}')
                continue
            if has_unresolved_threads(gh, num):
                print(f'AUTO_SKIP #{num}: unresolved review thread')
                continue
            if os.getenv('INTEGRATOR_APPLY') != 'true':
                print(f'AUTO_DRY_RUN #{num} SHA={head}')
                continue
            if gh.main_sha() != main_sha:
                print('HALT: main changed before automatic squash')
                return 0
            from protection_gate import allowed
            if not allowed(gh.get('/branches/main'), gh.get('/rules/branches/main?per_page=100')):
                print('HALT: protected main rules unverified')
                return 0
            fresh, fc, fr, ff, fm = gh.query_pr(num, head)
            qualified, reason = auto_eligible(fresh, fc, fr, ff, fm, main_sha)
            if not qualified or has_unresolved_threads(gh, num):
                print(f'AUTO_SKIP #{num}: stale evidence: {reason}')
                continue
            if gh.main_sha() != main_sha:
                print('HALT: main moved immediately before squash')
                return 0
            try:
                result = gh.squash(num, head)
            except urllib.error.HTTPError as error:
                if error.code in (405, 409, 422):
                    print(f'AUTO_SKIP #{num}: GitHub merge policy rejected ({error.code})')
                    continue
                raise
            if result.get('merged') is not True:
                raise ValueError('GitHub did not confirm automatic squash')
            new_main = result.get('sha')
            if not isinstance(new_main, str) or len(new_main) != 40:
                raise ValueError('GitHub did not supply complete merge SHA')
            if gh.main_sha() != new_main:
                print('HALT: main changed after merge; do not continue')
                return 0
            main_sha = new_main
            merged_count += 1
            merged_numbers.add(num)
            merged_this_step = True
            print(f'AUTO_MERGED #{num} SHA={new_main}')
            break
        if not merged_this_step:
            print(f'AUTO_BATCH_COMPLETE={merged_count}; no other verified candidates')
            return 0
    print(f'AUTO_BATCH_LIMIT={merged_count}; next event resumes discovery')
    return 0
