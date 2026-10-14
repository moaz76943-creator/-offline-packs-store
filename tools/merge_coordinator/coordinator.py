"""Fail-closed, exact-SHA public PR integration controller.

No unapproved PR is promoted or merged. Changes are intentionally limited to
repository-local decisions; no pack generation or source mutation occurs.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = 'moaz76943-creator/-offline-packs-store'
SHA = re.compile(r'[0-9a-f]{40}\Z')
SKIP = re.compile(r'\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\]|^skip-checks\s*:\s*true\s*$', re.I | re.M)
INTEGRATION_CONFIG = Path(__file__).with_name('approved.json')
DENY_PREFIXES = (
    'packs/', 'media/', 'assets/', 'legal/', 'community/',
    'tools/release_', 'tools/pack_manifest/', 'tools/ingestion_circuit_breaker/',
    'tools/open_export/', 'tools/pack_conformance/', 'tools/open_index/',
    'tools/gha_factory/', '.github/', 'catalog/', 'standards/',
)
DENY_EXACT = {'manifest.json', 'version.json', 'deutsch_deep_master.pack.gz',
              'perfect_public_store.py', 'pubspec.yaml', 'setup_repo.py'}


def policy_error(e):
    if not isinstance(e, dict):
        return 'malformed authorization'
    if not isinstance(e.get('number'), int) or e['number'] <= 0:
        return 'invalid PR number'
    if not all(isinstance(e.get(k), str) and SHA.fullmatch(e[k]) for k in ('head_sha', 'main_sha')):
        return 'invalid SHA authorization'
    if e.get('owner') != 'integration-coordinator':
        return 'not integration-coordinator owned'
    allowed = e.get('paths')
    if (not isinstance(allowed, list) or not allowed or
            not all(isinstance(path, str) for path in allowed) or
            len(set(allowed)) != len(allowed)):
        return 'empty, duplicated or malformed owned paths'
    for path in allowed:
        if not isinstance(path, str) or not path.endswith('/') or path.startswith('/') or '../' in path or '\\' in path:
            return 'unsafe allowed path'
        if not path.startswith(('tools/', 'tests/', 'docs/')) or path.startswith(DENY_PREFIXES):
            return 'prohibited owned path'
    names = e.get('checks')
    if (not isinstance(names, list) or len(names) < 2 or
            not all(isinstance(name, str) and name for name in names) or
            'public-pr-merge-gate' not in names or len(set(names)) != len(names)):
        return 'required primary and scoped checks missing'
    reviewers = e.get('reviewers')
    if not isinstance(reviewers, list) or not reviewers or not all(isinstance(x, str) and x for x in reviewers):
        return 'independent review not configured'
    for key in ('dependencies', 'excludes'):
        items = e.get(key)
        if not isinstance(items, list) or any(not isinstance(x, int) or x <= 0 or x == e['number'] for x in items):
            return 'invalid dependency/exclusion ids'
    if set(e['dependencies']) & set(e['excludes']):
        return 'dependency and exclusion overlap'
    return None


def order_entries(items):
    """Topologically sort authorized PRs with stable numeric tie-breaking."""
    by_id = {x['number']: x for x in items}
    if len(by_id) != len(items):
        raise ValueError('duplicate PR authorizations')
    order, grey, done = [], set(), set()

    def visit(n):
        if n in grey:
            raise ValueError('cyclic PR dependency')
        if n in done:
            return
        grey.add(n)
        for dep in sorted(by_id[n]['dependencies']):
            if dep in by_id:
                visit(dep)
        grey.remove(n)
        done.add(n)
        order.append(by_id[n])

    for key in sorted(by_id):
        visit(key)
    return order


def changed_path_names(files):
    """Original and resulting paths matter for ownership and collision checks."""
    if not isinstance(files, list):
        raise ValueError('file evidence is not a list')
    names = set()
    for file in files:
        if not isinstance(file, dict) or not isinstance(file.get('filename'), str):
            raise ValueError('malformed changed-file evidence')
        names.add(file['filename'])
        if file.get('status') in ('renamed', 'copied') or file.get('previous_filename') is not None:
            previous = file.get('previous_filename')
            if not isinstance(previous, str):
                raise ValueError('missing original path for rename/copy')
            names.add(previous)
    return names


def authorized_file_conflicts(gh, item, files, authorized):
    """Bounded read-only check for *actual* overlap with other authorized open PRs.

    Does not replace broad inventory triage or manual conflict decisions.
    """
    if len(authorized) > 25:
        raise ValueError('more than 25 authorized candidates; partition approval batch')
    mine = changed_path_names(files)
    conflicts = []
    for other in authorized:
        if other['number'] == item['number']:
            continue
        candidate = gh.get(f"/pulls/{other['number']}")
        if candidate.get('state') != 'open':
            continue
        theirs = changed_path_names(gh.page(f"/pulls/{other['number']}/files"))
        if mine & theirs:
            conflicts.append(other['number'])
    return sorted(conflicts)


def evaluate(e, pr, checks, reviews, files, main_sha, commit_message, dependencies, *, authorization_parent=None, authorization_only=False):
    """Pure readiness classifier; positive result is bound to exact PR/main SHAs."""
    err = policy_error(e)
    if err:
        return 'BLOCKED_POLICY', err
    if pr.get('number') != e['number'] or pr.get('state') != 'open':
        return 'NOT_VERIFIED', 'PR number or state changed'
    if pr.get('head', {}).get('sha') != e['head_sha']:
        return 'STALE_HEAD', 'PR head differs from authorized commit'
    authorized_main = (main_sha == e['main_sha'] or
                       (authorization_only and authorization_parent == e['main_sha']))
    if not authorized_main or pr.get('base', {}).get('ref') != 'main' or pr.get('base', {}).get('sha') != main_sha:
        return 'STALE_MAIN', 'canonical main advanced or base branch mismatched'
    if SKIP.search(commit_message):
        return 'BLOCKED_SKIP_CI', 'last PR commit skips required CI'
    if pr.get('mergeable') is False or pr.get('mergeable_state') == 'dirty':
        return 'CONFLICT', 'GitHub reports merge conflict'
    if pr.get('mergeable') is not True or pr.get('mergeable_state') not in ('clean', 'unstable'):
        return 'NOT_VERIFIED', 'mergeability unknown'
    if not isinstance(files, list) or not files:
        return 'SCOPE_VIOLATION', 'no inspectable changed files'
    for file in files:
        if not isinstance(file, dict):
            return 'SCOPE_VIOLATION', 'malformed changed file'
        names = [file.get('filename')]
        if file.get('status') in ('renamed', 'copied') or file.get('previous_filename') is not None:
            names.append(file.get('previous_filename'))
        for name in names:
            if (not isinstance(name, str) or name in DENY_EXACT or
                    name.startswith(DENY_PREFIXES) or
                    not any(name.startswith(prefix) for prefix in e['paths'])):
                return 'SCOPE_VIOLATION', f'unapproved or sensitive path {name}'
    for num in e['dependencies']:
        if dependencies.get(num, {}).get('merged') is not True:
            return 'BLOCKED_DEPENDENCY', f'#{num} is not merged'
    for num in e['excludes']:
        if dependencies.get(num, {}).get('state') == 'open':
            return 'SEMANTIC_CONFLICT', f'#{num} still open'
    runs = checks.get('check_runs', []) if isinstance(checks, dict) else []
    for wanted in e['checks']:
        eligible = [x for x in runs if x.get('name') == wanted and x.get('head_sha') == e['head_sha']
                    and x.get('app', {}).get('slug') == 'github-actions']
        latest = max(eligible, key=lambda x: x.get('id', 0), default=None)
        if latest is None or latest.get('status') != 'completed' or latest.get('conclusion') != 'success':
            return 'NOT_RUN', f'check {wanted} lacks exact-head PASS'
    if pr.get('draft'):
        return 'PROMOTE_ONLY', 'scoped and universal checks passed; re-evaluate after promotion'
    latest_review = {}
    for index, review in enumerate(reviews):
        if not isinstance(review, dict):
            continue
        login = (review.get('user') or {}).get('login')
        submitted = review.get('submitted_at')
        # Actual GitHub submissions are timestamped. Preserve order only for
        # older fixture records without timestamps; never let an older dated
        # approval override a newer dated CHANGES_REQUESTED event.
        key = (1, submitted, index) if isinstance(submitted, str) and submitted else (0, '', index)
        if login and (login not in latest_review or key > latest_review[login][0]):
            latest_review[login] = (key, review)
    author = (pr.get('user') or {}).get('login')
    approved = any(
        login != author and login in latest_review and
        latest_review[login][1].get('state') == 'APPROVED' and
        latest_review[login][1].get('commit_id') == e['head_sha']
        for login in e['reviewers']
    )
    if not approved:
        return 'NEEDS_REVIEW', 'no independent approval on exact head SHA'
    return 'VERIFIED_READY', 'exact-head validated'


class GitHub:
    def __init__(self):
        self.token = os.getenv('GITHUB_TOKEN', '')
        if not self.token:
            raise ValueError('GITHUB_TOKEN is required')

    def request(self, path, method='GET', data=None):
        if not path.startswith('/') or '://' in path:
            raise ValueError('unsafe GitHub endpoint')
        root = 'https://api.github.com'
        body = json.dumps(data).encode('utf-8') if data is not None else None
        req = urllib.request.Request(root + path, data=body, method=method, headers={
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {self.token}',
            'X-GitHub-Api-Version': '2022-11-28',
            'Content-Type': 'application/json',
            'User-Agent': 'deutsch-public-merge-coordinator',
        })
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)

    def get(self, path):
        return self.request(f'/repos/{REPO}{path}')

    def page(self, path, limit=300):
        out = []
        for n in range(1, limit // 100 + 2):
            records = self.get(f'{path}{"&" if "?" in path else "?"}per_page=100&page={n}')
            if not isinstance(records, list):
                raise ValueError('unexpected paginated response')
            out.extend(records)
            if len(out) > limit:
                raise ValueError('pagination limit exceeded; fail closed')
            if len(records) < 100:
                return out
        raise ValueError('pagination incomplete')

    def main_sha(self):
        return self.get('/git/ref/heads/main')['object']['sha']

    def authorization_origin(self, main_sha):
        main = self.get(f'/commits/{main_sha}')
        parents = main.get('parents', [])
        changed = main.get('files', [])
        approved_only = (len(parents) == 1 and len(changed) == 1 and
                         changed[0].get('filename') == 'tools/merge_coordinator/approved.json' and
                         changed[0].get('status') in ('modified', 'added'))
        return (parents[0]['sha'] if parents else None, approved_only)

    def query_pr(self, number, head_sha):
        pr = self.get(f'/pulls/{number}')
        checks = self.get(f'/commits/{head_sha}/check-runs?per_page=100')
        if checks.get('total_count', 0) > 100:
            raise ValueError('check runs pagination incomplete')
        reviews = self.page(f'/pulls/{number}/reviews')
        files = self.page(f'/pulls/{number}/files')
        commit = self.get(f'/commits/{head_sha}')
        return pr, checks, reviews, files, commit['commit']['message']

    def related_pr(self, n):
        p = self.get(f'/pulls/{n}')
        return {'state': p['state'], 'merged': p['merged']}

    def promote(self, number):
        pr = self.get(f'/pulls/{number}')
        body = {'query': 'mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{isDraft}}}',
                'variables': {'id': pr['node_id']}}
        result = self.request('/graphql', method='POST', data=body)
        if result.get('errors') or result.get('data', {}).get('markPullRequestReadyForReview', {}).get('pullRequest', {}).get('isDraft') is not False:
            raise ValueError('promotion not confirmed')

    def squash(self, number, head):
        return self.request(f'/repos/{REPO}/pulls/{number}/merge', method='PUT', data={
            'sha': head, 'merge_method': 'squash',
            'commit_title': f'integrate: verified public PR #{number}',
            'commit_message': f'Exact head verified: {head}. Independent review and scoped QA confirmed.'
        })


def run():
    approved = json.loads(INTEGRATION_CONFIG.read_text(encoding='utf-8'))
    if not isinstance(approved, dict) or approved.get('schema') != 1 or not isinstance(approved.get('prs'), list):
        raise ValueError('malformed integration approval registry')
    items = approved['prs']
    for item in items:
        why = policy_error(item)
        if why:
            raise ValueError(f"authorization #{item.get('number')} invalid: {why}")
    ordered = order_entries(items)
    gh = GitHub()
    original_main = gh.main_sha()
    auth_parent, auth_only = gh.authorization_origin(original_main)
    print(f'MAIN={original_main} APPROVED_CANDIDATES={len(ordered)}')
    for item in ordered:
        number = item['number']
        if gh.main_sha() != original_main:
            print('HALT: main changed concurrently; defer whole remaining batch')
            return 0
        try:
            pr, checks, reviews, files, commit_message = gh.query_pr(number, item['head_sha'])
            related = {n: gh.related_pr(n) for n in set(item['dependencies'] + item['excludes'])}
            result, reason = evaluate(item, pr, checks, reviews, files, original_main, commit_message, related,
                                      authorization_parent=auth_parent, authorization_only=auth_only)
            print(f'PR=#{number} SHA={item["head_sha"]} STATUS={result}: {reason}')
            if result in ('PROMOTE_ONLY', 'VERIFIED_READY'):
                overlap = authorized_file_conflicts(gh, item, files, ordered)
                if overlap:
                    print(f'BLOCKED_PATH_CONFLICT #{number}: authorized open PRs {overlap} touch identical files')
                    continue
            if result == 'PROMOTE_ONLY':
                if os.getenv('INTEGRATOR_APPLY') == 'true':
                    if gh.main_sha() != original_main or gh.get(f'/pulls/{number}')['head']['sha'] != item['head_sha']:
                        print('HALT: SHA changed before promotion')
                        return 0
                    gh.promote(number)
                    print(f'PROMOTED #{number}; stop until new review and checks complete')
                    return 0
            elif result == 'VERIFIED_READY':
                if os.getenv('INTEGRATOR_APPLY') != 'true':
                    print('DRY RUN ONLY; no merge')
                    continue
                if gh.main_sha() != original_main:
                    print('HALT: main moved; do not merge')
                    return 0
                p, c, rev, f, msg = gh.query_pr(number, item['head_sha'])
                # Dependencies/exclusions must be re-read: preliminary results
                # are not authorization for a later privileged transition.
                fresh_related = {n: gh.related_pr(n) for n in
                                 set(item['dependencies'] + item['excludes'])}
                fresh_main = gh.main_sha()
                fresh, why = evaluate(item, p, c, rev, f, fresh_main, msg, fresh_related,
                                      authorization_parent=auth_parent, authorization_only=auth_only)
                if fresh != 'VERIFIED_READY':
                    print(f'HALT: changed evidence {fresh} {why}')
                    return 0
                overlap = authorized_file_conflicts(gh, item, f, ordered)
                if overlap:
                    print(f'HALT: authorized file overlap changed before squash: {overlap}')
                    return 0
                if gh.main_sha() != original_main:
                    print('HALT: main changed immediately before squash')
                    return 0
                result = gh.squash(number, item['head_sha'])
                if result.get('merged') is not True:
                    raise ValueError(f'GitHub did not confirm merge for #{number}')
                new_head = gh.main_sha()
                if new_head != result.get('sha'):
                    print(f'WARNING: external main movement after merge: {new_head}')
                print(f'MERGED #{number} HEAD={new_head} GH_MERGE_SHA={result.get("sha")}')
                return 0
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError) as ex:
            print(f'BLOCKED #{number}: GitHub evidence unavailable: {ex}', file=sys.stderr)
            continue
    print('NO QUALIFIED MERGE; no repository files or pack bytes changed')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(run())
    except (ValueError, OSError, urllib.error.URLError) as exc:
        print(f'FAIL CLOSED: {exc}', file=sys.stderr)
        raise SystemExit(2)
