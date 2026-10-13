#!/usr/bin/env python3
"""Automatically enqueue ONLY already admitted public corpus partitions.

Consumes GHA-01 immutable queue manifests through GHA-02 controller.context.
Creates owner-authored GitHub Issues using the unchanged queue v1 contract.
No download, corpus generation, manifest changes or production publication.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

from tools.gha_factory.dispatcher import controller, queue

REPO = controller.REPO
OWNER = controller.OWNER
MAX_NEW_ISSUES = 5
MAX_SCAN_PAGES = 6
MAX_RESPONSE = 2_000_000


def proposal(source_id, language, source_sha, shard):
    item = {
        'schema_version': queue.VERSION,
        'source_sha256': source_sha,
        'source_id': source_id,
        'language': language,
        'task_type': 'admission_partition_verify',
        'shard': shard,
        'contract_version': queue.CONTRACT,
        'state': 'READY',
        'attempts': 0,
        'next_retry_at': None,
        'lease_until': None,
        'run_id': None,
        'run_attempt': None,
        'checkpoint': 0,
        'receipt': None,
    }
    item['task_id'] = queue.fingerprint(item)
    return queue.validate(item)


def _existing_issues(items):
    known = {}
    for issue in items:
        if (not isinstance(issue, dict)
                or issue.get('pull_request')
                or (issue.get('user') or {}).get('login') != OWNER
                or not issue.get('title', '').startswith(queue.PREFIX)):
            continue
        task = queue.parse(issue.get('body'))
        if issue['title'] != queue.PREFIX + task['task_id']:
            raise ValueError('owner-authored queue issue title/body mismatch')
        prior = known.get(task['task_id'])
        if prior is not None:
            if prior != task['source_id']:
                raise ValueError('source-ID fingerprint collision in existing issues')
            raise ValueError('duplicate pre-existing queue issue; halt seeding')
        known[task['task_id']] = task['source_id']
    return known


def plan(context, registry_sha, issues, limit=MAX_NEW_ISSUES):
    """Return ≤5 new deterministic queue v1 tasks, never speculative source jobs."""
    if type(limit) is not int or not 1 <= limit <= MAX_NEW_ISSUES:
        raise ValueError('invalid bounded enqueue limit')
    known = _existing_issues(issues)
    proposed = []
    identities = {}
    for key in sorted(context.get('admissions', {})):
        if not isinstance(key, tuple) or len(key) != 4:
            raise ValueError('invalid immutable partition identity')
        sid, lang, digest, shard = key
        item = proposal(sid, lang, digest, shard)
        # The existing GHA-02 gate also validates approved source ledger,
        # stable registry identity, and admission report identity.
        if queue.admission(item, context, registry_sha) != 'READY':
            continue
        prior = identities.get(item['task_id'])
        if prior is not None and prior != sid:
            raise ValueError('source-ID fingerprint collision; queue v1 migration needed')
        identities[item['task_id']] = sid
        existing_sid = known.get(item['task_id'])
        if existing_sid is not None:
            if existing_sid != sid:
                raise ValueError('source-ID fingerprint collision with an existing issue')
            continue
        proposed.append(item)
        if len(proposed) == limit:
            break
    return proposed


class GitHubIssueWriter:
    def __init__(self, token):
        if not isinstance(token, str) or not token:
            raise ValueError('GitHub token required')
        self.token = token
        self.base = 'https://api.github.com/repos/' + REPO

    def request(self, path, body=None):
        if not (path == '/issues' or
                (path.startswith('/issues?state=all&per_page=100&page=')
                 and path.rsplit('=', 1)[-1] in {str(i) for i in range(1, MAX_SCAN_PAGES + 2)})):
            raise ValueError('unsafe GitHub API endpoint')
        if body is not None and path != '/issues':
            raise ValueError('write outside verified issue creation endpoint')
        raw_body = None if body is None else json.dumps(body, separators=(',', ':')).encode('utf-8')
        if raw_body is not None and len(raw_body) > 12_500:
            raise ValueError('oversized issue body')
        req = urllib.request.Request(
            self.base + path,
            data=raw_body,
            method='POST' if body is not None else 'GET',
            headers={
                'Authorization': 'Bearer ' + self.token,
                'Accept': 'application/vnd.github+json',
                'Content-Type': 'application/json',
                'X-GitHub-Api-Version': '2022-11-28',
                'User-Agent': 'public-source-queue-autoseed',
            },
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            data = response.read(MAX_RESPONSE + 1)
            if len(data) > MAX_RESPONSE:
                raise ValueError('oversized GitHub Issues response')
            if body is not None and response.status != 201:
                raise ValueError('unexpected GitHub issue creation response')
        return json.loads(data)

    def all_queue_issues(self):
        # Closed SUCCEEDED issues also count: never accidentally requeue them.
        all_issues = []
        for page in range(1, MAX_SCAN_PAGES + 2):
            page_items = self.request(f'/issues?state=all&per_page=100&page={page}')
            if not isinstance(page_items, list):
                raise ValueError('invalid issue listing')
            if page == MAX_SCAN_PAGES + 1 and page_items:
                raise ValueError('GitHub issue inventory exceeds safe pagination bound')
            all_issues.extend(page_items)
            if len(page_items) < 100:
                break
        return all_issues

    def create(self, task):
        queue.validate(task)
        if task['task_type'] != 'admission_partition_verify' or task['state'] != 'READY':
            raise ValueError('refusing to create unadmitted/non-ready issue')
        body = {'title': queue.PREFIX + task['task_id'], 'body': queue.serialize(task)}
        result = self.request('/issues', body)
        if result.get('title') != body['title'] or not isinstance(result.get('number'), int):
            raise ValueError('GitHub issue creation cannot be verified')
        return result['number']


def main():
    if (os.getenv('GITHUB_REPOSITORY') != REPO or
            os.getenv('GITHUB_REF') != 'refs/heads/main'):
        raise ValueError('only the canonical public repository main may seed')
    context, registry_sha = controller.context()
    writer = GitHubIssueWriter(os.getenv('GITHUB_TOKEN'))
    issues = writer.all_queue_issues()
    new = plan(context, registry_sha, issues)
    numbers = []
    for task in new:
        numbers.append(writer.create(task))
    print(json.dumps({
        'status': 'SEEDED' if numbers else 'NO_APPROVED_NEW_PARTITIONS',
        'new_issue_numbers': numbers,
        'new_issue_count': len(numbers),
        'admitted_partition_count': len(context.get('admissions', {})),
        'production_publication': False,
    }, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print('FAIL_CLOSED_AUTOSEED: ' + str(error), file=sys.stderr)
        sys.exit(1)
