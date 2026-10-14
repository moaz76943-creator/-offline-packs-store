#!/usr/bin/env python3
"""Read-only, fail-closed pull-request merge backlog inventory.

This does not promote, approve, merge, close, retarget, or modify PRs.
It is a diagnostic companion to the incumbent protected merge coordinator.
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

PUBLIC = 'moaz76943-creator/-offline-packs-store'
PRIVATE = 'moaz76943-creator/deutsch-build'
EXPECTED = {PUBLIC: 'main', PRIVATE: 'staging/v2-full-platform'}
SKIP = re.compile(r'\[(?:skip ci|ci skip|no ci|skip actions|actions skip)\]|^skip-checks\s*:\s*true\s*$', re.I | re.M)
SENSITIVE_PREFIXES = (
    '.github/', 'legal/', 'packs/', 'media/', 'assets/', 'catalog/',
    'standards/', 'tools/gha_factory/', 'tools/release_',
    'tools/merge_coordinator/', 'tools/ci_policy/', 'tools/open_export/',
    'community/', 'lib/', 'android/',
)
SENSITIVE_EXACT = ('manifest.json', 'version.json')
MAX_PAGES = 10


class GitHubReadOnly:
    """Small bounded HTTPS client, GET requests only."""
    def __init__(self, repository, token=None):
        if repository not in EXPECTED:
            raise ValueError('repository not approved')
        self.repository = repository
        self.token = token or ''

    def get(self, path):
        if not path.startswith('/') or '\\' in path or '://' in path or '..' in path:
            raise ValueError('invalid API path')
        uri = 'https://api.github.com/repos/' + self.repository + path
        headers = {'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28',
                   'User-Agent': 'deutsch-merge-backlog-readonly'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request(uri, headers=headers, method='GET')
        with urllib.request.urlopen(request, timeout=18) as response:
            return json.load(response)


def get_pages(client, path, max_pages=MAX_PAGES, array_key=None):
    """Fail rather than truncate a paginated result at a bound."""
    if max_pages < 1:
        raise ValueError('invalid page bound')
    all_items = []
    for page in range(1, max_pages + 1):
        join = '&' if '?' in path else '?'
        response = client.get(path + f'{join}per_page=100&page={page}')
        result = response.get(array_key) if array_key and isinstance(response, dict) else response
        if not isinstance(result, list):
            raise ValueError('GitHub did not return a list')
        all_items.extend(result)
        if len(result) < 100:
            return all_items
    raise ValueError('pagination not proven complete')


def overlaps(files_by_pr):
    """O(total changed paths), not an all-vs-all PR comparison."""
    by_file = defaultdict(set)
    for pr_number, paths in files_by_pr.items():
        for path in paths:
            by_file[path].add(pr_number)
    return {p: sorted(nums) for p, nums in sorted(by_file.items()) if len(nums) > 1}


def classify(pr, final_message, checks, reviews, required_checks, expected_base, changed_files):
    """Classify evidence without claiming PR is authorized or GitHub-mergeable."""
    sha = ((pr.get('head') or {}).get('sha') or '')
    number = pr.get('number')
    blockers = []
    def block(reason):
        if reason not in blockers:
            blockers.append(reason)

    if pr.get('state', 'open') != 'open' or not re.fullmatch('[0-9a-f]{40}', sha):
        block('UNVERIFIED_IDENTITY')
    if ((pr.get('base') or {}).get('ref') != expected_base):
        block('BASE_REVIEW_REQUIRED')
    if pr.get('draft') is True:
        block('DRAFT')
    if pr.get('mergeable') is False:
        block('CONFLICT')
    elif pr.get('mergeable') is not True:
        block('MERGEABILITY_UNKNOWN')
    if final_message is None:
        block('TIP_MESSAGE_UNKNOWN')
    elif SKIP.search(final_message):
        block('SKIP_CI_TIP')
    if changed_files is None or not isinstance(changed_files, list):
        block('FILES_UNVERIFIED')
    elif not changed_files:
        block('EMPTY_DIFF')
    elif any(any(p.startswith(prefix) for prefix in SENSITIVE_PREFIXES) or p in SENSITIVE_EXACT
             for p in changed_files):
        block('SENSITIVE_SCOPE')

    if not required_checks:
        block('CI_POLICY_UNVERIFIED')
    for name in required_checks:
        same = [c for c in (checks or []) if c.get('name') == name
                and c.get('head_sha') == sha
                and (c.get('app') or {}).get('slug') == 'github-actions']
        latest = max(same, key=lambda c: c.get('id') or 0, default=None)
        if latest is None:
            block('NOT_RUN:' + name)
        elif latest.get('status') != 'completed':
            block('CI_PENDING:' + name)
        elif latest.get('conclusion') != 'success':
            block('CI_FAIL:' + name)

    author = ((pr.get('user') or {}).get('login') or '').lower()
    last_review = {}
    for r in sorted(reviews or [], key=lambda x: x.get('id') or 0):
        login = ((r.get('user') or {}).get('login') or '').lower()
        if login:
            last_review[login] = r
    if not any(login != author and r.get('state') == 'APPROVED'
               and r.get('commit_id') == sha for login, r in last_review.items()):
        block('INDEPENDENT_REVIEW_REQUIRED')
    return {'number': number, 'base': (pr.get('base') or {}).get('ref'),
            'head_sha': sha, 'title': pr.get('title'),
            'blockers': blockers,
            'status': 'BLOCKED' if blockers else 'REVIEWED_CANDIDATE_NOT_AUTHORIZED'}


def read_repository(repo, client, deep_limit, expected_base=None):
    expected_base = expected_base or EXPECTED[repo]
    original_sha = client.get('/git/ref/heads/' + urllib.parse.quote(expected_base, safe='/'))['object']['sha']
    prs = get_pages(client, '/pulls?state=open', max_pages=MAX_PAGES)
    results = []
    files_by_pr = {}
    for position, summary in enumerate(prs):
        number = summary['number']
        if position >= deep_limit:
            results.append({'number': number, 'title': summary.get('title'),
                            'base': (summary.get('base') or {}).get('ref'),
                            'head_sha': (summary.get('head') or {}).get('sha'),
                            'status': 'NOT_FULLY_AUDITED',
                            'blockers': ['DEEP_AUDIT_NOT_RUN']})
            continue
        try:
            pr = client.get(f'/pulls/{number}')
            sha = (pr.get('head') or {}).get('sha', '')
            if not re.fullmatch('[0-9a-f]{40}', sha):
                raise ValueError('invalid head sha')
            commit = client.get('/commits/' + sha)
            checks = get_pages(client, '/commits/' + sha + '/check-runs', MAX_PAGES, array_key='check_runs')
            reviews = get_pages(client, f'/pulls/{number}/reviews', MAX_PAGES)
            changed = get_pages(client, f'/pulls/{number}/files', MAX_PAGES)
            filenames = [f['filename'] for f in changed]
            if len(set(filenames)) != len(filenames):
                raise ValueError('duplicate changed filename')
            pr_after = client.get(f'/pulls/{number}')
            if (pr_after.get('head') or {}).get('sha') != sha:
                raise ValueError('head changed during audit')
            files_by_pr[number] = filenames
            # Scope-sensitive PRs require additional checks and a source-specific
            # reviewer even when the general gate passes. No auto-authorization.
            required = ('public-pr-merge-gate',) if repo == PUBLIC else ()
            results.append(classify(pr, (commit.get('commit') or {}).get('message'),
                                    checks, reviews, required, expected_base, filenames))
        except (ValueError, KeyError, TypeError, urllib.error.HTTPError, urllib.error.URLError) as e:
            results.append({'number': number, 'title': summary.get('title'),
                            'head_sha': (summary.get('head') or {}).get('sha'),
                            'status': 'AUDIT_ERROR', 'blockers': ['EVIDENCE_UNAVAILABLE'],
                            'error_type': type(e).__name__})
    latest_sha = client.get('/git/ref/heads/' + urllib.parse.quote(expected_base, safe='/'))['object']['sha']
    if latest_sha != original_sha:
        for result in results:
            result['status'] = 'STALE_BASE_SNAPSHOT'
            if 'STALE_BASE_SNAPSHOT' not in result['blockers']:
                result['blockers'].append('STALE_BASE_SNAPSHOT')
    return {'repository': repo, 'expected_base': expected_base,
            'base_sha_before': original_sha, 'base_sha_after': latest_sha,
            'open_prs': len(prs), 'deep_audited': min(len(prs), deep_limit),
            'file_overlaps': overlaps(files_by_pr), 'prs': results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deep', type=int, default=10, help='Deep-audit first N PRs per repository (default 10)')
    parser.add_argument('--include-private', action='store_true', help='Private repo only with explicit opt-in and token')
    parser.add_argument('--output', help='Local JSON report file; never commit private reports to public repositories')
    args = parser.parse_args(argv)
    if not 0 <= args.deep <= 1000:
        parser.error('--deep must be between 0 and 1000')
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if args.include_private and not token:
        parser.error('private inventory requires GH_TOKEN or GITHUB_TOKEN')
    repos = [PUBLIC] + ([PRIVATE] if args.include_private else [])
    try:
        results = [read_repository(repo, GitHubReadOnly(repo, token), args.deep) for repo in repos]
    except (ValueError, KeyError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        print('FAIL CLOSED: inventory unavailable: ' + type(exc).__name__, file=sys.stderr)
        return 2
    report = {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'readonly': True, 'authorization_to_merge': False,
              'results': results}
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, 'x', encoding='utf-8') as stream:
            stream.write(serialized + '\n')
    else:
        print(serialized)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())