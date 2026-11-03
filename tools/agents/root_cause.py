"""Record a failure signature and its structural cause.

A repeated signature opens one issue. It does not rerun the failed job.
ROOT_CAUSES.md, when another agent owns that file, wins over a new issue.
"""

import json
import re
import subprocess

from tools.agents.common import SCHEMA_VERSION


def select_active_failures(runs, cap=3):
    """Select newest actionable failure per workflow and independent PR scope.

    A verified newer success or an active newer run on *that same scope*
    supersedes the old failure. Skipped checks prove nothing and never
    suppress an earlier failure. The inventory is newest-first (GitHub API).
    """
    import hashlib

    if type(cap) is not int or not 1 <= cap <= 3:
        raise ValueError('failure-sweep cap must be 1..3')
    if not isinstance(runs, list):
        raise ValueError('GitHub run inventory must be a list')
    latest = {}
    pr_events = {'pull_request', 'pull_request_target', 'pull_request_review'}
    for row in runs:
        if not isinstance(row, dict):
            continue
        name = row.get('workflowName') or row.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            continue
        if name.casefold() == 'agent health':
            continue
        # A skipped run is not evidence of remediation.
        if row.get('status') == 'completed' and row.get('conclusion') == 'skipped':
            continue
        event = row.get('event') or 'unknown'
        if event in pr_events:
            pr = row.get('pullRequest')
            repository = row.get('headRepository')
            branch = row.get('headBranch')
            sha = row.get('headSha')
            if type(pr) is int and pr > 0:
                scope = (name, event, 'pr', pr)
                signature = f'{name[:52]} PR #{pr}'
            elif (isinstance(repository, str) and repository
                    and len(repository) <= 160 and isinstance(branch, str)
                    and branch and len(branch) <= 180):
                scope = (name, event, 'branch', repository, branch)
                fingerprint = hashlib.sha256((repository + '/' + branch).encode()).hexdigest()[:10]
                signature = f'{name[:24]} {repository[:18]}:{branch[:12]}-{fingerprint}'
            elif isinstance(sha, str) and re.fullmatch('[0-9a-f]{40}', sha):
                scope = (name, event, 'sha', sha)
                signature = f'{name[:52]} sha-{sha[:12]}'
            else:
                # Never merge two unidentifiable PRs into one health task.
                continue
        else:
            branch = row.get('headBranch') or ''
            if not isinstance(branch, str):
                continue
            scope = (name, event, 'branch', branch)
            if event == 'unknown':
                signature = name
            else:
                fingerprint = hashlib.sha256((event + '/' + branch).encode()).hexdigest()[:8]
                signature = f'{name[:40]} {event[:12]}:{branch[:12]}-{fingerprint}'
        if scope not in latest:
            latest[scope] = (row, signature)

    selected = []
    for row, signature in latest.values():
        if row.get('status') != 'completed' or row.get('conclusion') != 'failure':
            continue
        run_id = row.get('databaseId')
        if type(run_id) is not int or run_id <= 0:
            continue
        selected.append({'databaseId': run_id, 'name': signature})
        if len(selected) == cap:
            break
    return selected


def signature_id(signature):
    text = re.sub(r'[^a-z0-9]+', '-', (signature or 'unknown').lower()).strip('-')
    return (text or 'unknown')[:80]


def classify(signature):
    """Map a signature to a cause that removes the class, not a retry."""
    text = (signature or '').lower()
    if 'license_notice' in text or 'no module named' in text:
        return {
            'root_cause': (
                'A test module imports license_notice as a sibling. '
                'From the repository root that name is not a package.'
            ),
            'structural_fix': (
                'Run python3 -m unittest tools.agents.test_agents from the repository root. '
                'Run the ledger tests from legal/ledger. Do not import them in the agent workflow.'
            ),
        }
    if 'non-fast-forward' in text or 'failed to push' in text:
        return {
            'root_cause': 'Two publishers committed the same path on agents/data.',
            'structural_fix': (
                'Each agent writes only state/agents/<name>.json and data/agents/<name>/. '
                'One merge integrates disjoint files. Do not loop the push.'
            ),
        }
    if '429' in text or 'rate limit' in text:
        return {
            'root_cause': 'The same concept was requested once per language shard.',
            'structural_fix': (
                'Read the shared data/agents/harvest cache. Do not repeat the request in the failing job.'
            ),
        }
    if 'timeout' in text or 'curl' in text:
        return {
            'root_cause': 'A job read a shared remote slice and would retry a smaller range of the same URL.',
            'structural_fix': (
                'Write one file per shard and stop after a failed read. '
                'A smaller retry of the same URL does not remove the failure class.'
            ),
        }
    return {
        'root_cause': f'The run failed with signature {signature or "unknown"}.',
        'structural_fix': (
            'Change the producer so this signature cannot recur: one output file per shard, '
            'schema_version on the contract, and a regression test. Do not rerun the job.'
        ),
    }


def documented_in_root_causes(root_causes_text, signature):
    """True when the backlog agent's ROOT_CAUSES.md already names this signature."""
    if not root_causes_text:
        return False
    return signature_id(signature) in root_causes_text.lower()


def repair_update(record, signature, run_id='', root_causes_text=''):
    """Count a new run id once. The second distinct run asks for one issue."""
    record = record if isinstance(record, dict) else {}
    sid = signature_id(signature)
    classified = classify(signature)
    seen = int(record.get('seen_count') or 0)
    last_run = str(record.get('last_run_id') or '')
    if not (run_id and run_id == last_run):
        seen += 1
    issue_number = record.get('issue_number')
    documented = documented_in_root_causes(root_causes_text, signature)
    if documented or issue_number:
        action = 'already-tracked'
    elif seen >= 2:
        action = 'open-root-cause-issue'
    else:
        action = 'recorded'
    plan = {
        'schema_version': SCHEMA_VERSION,
        'signature': sid,
        'raw_signature': signature or 'unknown',
        'root_cause': classified['root_cause'],
        'structural_fix': classified['structural_fix'],
        'seen_count': seen,
        'last_run_id': str(run_id or last_run),
        'action': action,
        'retries': 0,
        'issue_title': f'Root cause: {sid}',
        'issue_number': issue_number,
        'tracked_in': 'ROOT_CAUSES.md' if documented else '',
    }
    plan['issue_body'] = (
        f'## Signature\n`{sid}`\n\n'
        f'## Root cause\n{plan["root_cause"]}\n\n'
        f'## Structural fix\n{plan["structural_fix"]}\n\n'
        'One issue per signature. If ROOT_CAUSES.md already describes this cause, close this issue.\n'
    )
    return plan, plan


def _default_runner(args):
    return subprocess.check_output(['gh', *args], text=True)


def open_recorded_issue(plan, runner=None):
    """Open at most one issue. An existing title or number is the tracker."""
    plan = dict(plan)
    if plan.get('action') != 'open-root-cause-issue' or plan.get('issue_number'):
        if plan.get('issue_number'):
            plan['action'] = 'already-tracked'
        return plan
    run = runner or _default_runner
    title = plan['issue_title']
    listed = run(['issue', 'list', '--state', 'all', '--limit', '20', '--search', f'in:title {title}', '--json', 'number,title'])
    matches = json.loads(listed or '[]')
    existing = next((item.get('number') for item in matches if item.get('title') == title), None)
    if existing:
        plan['issue_number'] = existing
        plan['action'] = 'already-tracked'
        return plan
    created = run(['issue', 'create', '--title', title, '--body', plan.get('issue_body') or title])
    match = re.search(r'/issues/(\d+)', created or '')
    if match:
        plan['issue_number'] = int(match.group(1))
        plan['action'] = 'already-tracked'
    return plan
