"""Read-only independent-run handoff contract atop existing GHA-02 Issue ledger.

This is not a queue or production worker. Mutations are owned by the existing
dispatcher; tickets here do not confer authority to claim, execute or publish.
"""
import hashlib
import importlib
import json
import re
from datetime import timedelta
from tools.gha_factory.dispatcher import queue as v1

REPO = 'moaz76943-creator/-offline-packs-store'
WORKFLOW = '.github/workflows/factory_worker_handoff_qa.yml'
TRUSTED_CREATORS = frozenset(('moaz76943-creator', 'github-actions[bot]'))
EXECUTABLE_V1 = frozenset(('registry_validate', 'admission_partition_verify'))
EXECUTABLE_V2 = frozenset(('registry_validate', 'admission_partition_verify', 'approved_snapshot_verify'))
MAX_WORKERS = 3
MAX_ATTEMPTS = 3
MAX_LEASE_SECONDS = 6 * 3600
HEX = re.compile(r'^[0-9a-f]{64}$')
FIELDS = frozenset(('schema_version', 'issue_number', 'task_id', 'source_id',
                    'source_sha256', 'language', 'task_type', 'shard',
                    'controller_run_id', 'controller_attempt', 'worker_run_id',
                    'worker_attempt', 'checkout_sha', 'checkpoint', 'checkpoint_sha256'))


def _positive(value):
    return type(value) is int and value > 0


def _sha(value):
    return isinstance(value, str) and HEX.fullmatch(value) is not None


def _parse(body):
    if not isinstance(body, str) or len(body.encode('utf-8')) > 12000:
        raise ValueError('oversized/invalid Issue task')
    if body.startswith(v1.MARKER):
        # PR #81 is not merged: guard its duplicate-field vulnerability here.
        def no_duplicate_keys(pairs):
            data = {}
            for key, value in pairs:
                if key in data:
                    raise ValueError('duplicate JSON field')
                data[key] = value
            return data
        json.loads(body[len(v1.MARKER):-4], object_pairs_hook=no_duplicate_keys)
        return v1.parse(body)
    if body.startswith('```gha-task-v2\n'):
        # Reuse the PR #74 parser after integration. No competing v2 queue.
        try:
            module = importlib.import_module('tools.gha_factory.orchestration.protocol')
        except ImportError as error:
            raise ValueError('v2 orchestration protocol is not integrated') from error
        return module.parse(body)
    raise ValueError('unsupported Issue task envelope')


def trusted_task(issue):
    if not isinstance(issue, dict) or 'pull_request' in issue or not _positive(issue.get('number')):
        raise ValueError('not a trusted Issue')
    if (issue.get('user') or {}).get('login') not in TRUSTED_CREATORS:
        raise ValueError('untrusted Issue creator')
    task = _parse(issue.get('body'))
    if issue.get('title') != v1.PREFIX + task['task_id']:
        raise ValueError('Issue title/task identity mismatch')
    return task


def ticket(issue, worker_run, checkout_sha, now):
    """Describe an independently dispatched run, never create a new claim."""
    task = trusted_task(issue)
    if task['state'] not in ('CLAIMED', 'RUNNING'):
        raise ValueError('Issue is not leased')
    if not _positive(task['run_id']) or not _positive(task['run_attempt']):
        raise ValueError('missing controller lease owner')
    if not (0 < task['attempts'] <= MAX_ATTEMPTS):
        raise ValueError('invalid retry count')
    allowed = EXECUTABLE_V1 if task['schema_version'] == '1.0' else EXECUTABLE_V2
    if task['task_type'] not in allowed:
        raise ValueError('unintegrated worker kind')
    expiry = v1.date_value(task['lease_until'])
    if expiry is None or expiry <= now or expiry > now + timedelta(seconds=MAX_LEASE_SECONDS):
        raise ValueError('expired/implausible lease')
    if not _sha(checkout_sha):
        raise ValueError('checkout SHA missing')
    if (not isinstance(worker_run, dict) or not _positive(worker_run.get('id'))
            or not _positive(worker_run.get('run_attempt'))
            or worker_run.get('path') != WORKFLOW
            or worker_run.get('event') != 'workflow_dispatch'
            or worker_run.get('head_branch') != 'main'
            or worker_run.get('head_sha') != checkout_sha
            or worker_run.get('status') not in ('queued', 'in_progress', 'completed')
            or (worker_run.get('status') == 'completed' and worker_run.get('conclusion') != 'success')):
        raise ValueError('unverified independent worker run')
    if worker_run['id'] == task['run_id']:
        raise ValueError('worker is not independent of controller')
    return validate_ticket({
        'schema_version': task['schema_version'], 'issue_number': issue['number'],
        'task_id': task['task_id'], 'source_id': task['source_id'],
        'source_sha256': task['source_sha256'], 'language': task['language'],
        'task_type': task['task_type'], 'shard': task['shard'],
        'controller_run_id': task['run_id'], 'controller_attempt': task['run_attempt'],
        'worker_run_id': worker_run['id'], 'worker_attempt': worker_run['run_attempt'],
        'checkout_sha': checkout_sha, 'checkpoint': task['checkpoint'],
        'checkpoint_sha256': None,
    })


def validate_ticket(t):
    if not isinstance(t, dict) or set(t) != FIELDS:
        raise ValueError('unexpected handoff fields')
    if t['schema_version'] not in ('1.0', '2.0'):
        raise ValueError('unsupported schema')
    for key in ('issue_number', 'controller_run_id', 'controller_attempt', 'worker_run_id', 'worker_attempt'):
        if not _positive(t[key]):
            raise ValueError('invalid run/Issue identity')
    for key in ('task_id', 'source_sha256', 'checkout_sha'):
        if not _sha(t[key]):
            raise ValueError('invalid identity SHA')
    if t['checkpoint_sha256'] is not None and not _sha(t['checkpoint_sha256']):
        raise ValueError('invalid checkpoint SHA')
    if (not isinstance(t['source_id'], str) or not v1.SOURCE.fullmatch(t['source_id'])
            or not isinstance(t['language'], str) or not v1.LANG.fullmatch(t['language'])
            or type(t['shard']) is not int or not 0 <= t['shard'] < 100000
            or type(t['checkpoint']) is not int or not 0 <= t['checkpoint'] <= 10000):
        raise ValueError('invalid source/language/checkpoint')
    allowed = EXECUTABLE_V1 if t['schema_version'] == '1.0' else EXECUTABLE_V2
    if t['task_type'] not in allowed or t['controller_run_id'] == t['worker_run_id']:
        raise ValueError('unsupported worker or non-independent run')
    return t


def validate_against_issue(handoff, issue, run, now):
    """Re-read authoritative Issue/run state; reject old run-attempt tickets."""
    validate_ticket(handoff)
    fresh = ticket(issue, run, handoff['checkout_sha'], now)
    fresh['checkpoint_sha256'] = handoff['checkpoint_sha256']
    if fresh != handoff:
        raise ValueError('stale handoff/changed lease')
    return fresh


def fair_claim_candidates(entries, active, limit=MAX_WORKERS):
    """Pure selection: caller must supply GH-verified active runs."""
    if type(limit) is not int or not 1 <= limit <= MAX_WORKERS:
        raise ValueError('capacity escalation requires independent review')
    if not isinstance(active, list) or not isinstance(entries, list):
        raise ValueError('invalid inventory')
    if len(entries) > 2000 or len(active) > 2000:
        raise ValueError('unbounded inventory')
    locks = set()
    active_ids = set()
    for t in active:
        if t.get('state') not in ('CLAIMED', 'RUNNING') or not _sha(t.get('task_id')):
            raise ValueError('unverified active lease')
        locks.add((t['source_id'], t['language']))
        active_ids.add(t['task_id'])
    if len(active) > limit:
        raise ValueError('worker capacity already exceeded')
    found = set()
    result = []
    for number, t in sorted(entries, key=lambda x: (x[1]['attempts'], x[0])):
        if not _positive(number) or not _sha(t.get('task_id')):
            raise ValueError('invalid issue identity')
        if t['task_id'] in found:
            raise ValueError('ambiguous duplicate task identity')
        found.add(t['task_id'])
        if t['task_id'] in active_ids:
            if t['state'] not in ('CLAIMED', 'RUNNING'):
                raise ValueError('active worker has contradictory Issue state')
            continue
        lock = (t['source_id'], t['language'])
        if (t['state'] == 'READY' and t['attempts'] < MAX_ATTEMPTS
                and lock not in locks and len(result) + len(active) < limit):
            result.append((number, t))
            locks.add(lock)
    return result


def durable_checkpoint(handoff, saved, blob):
    """No resume without externally restored SHA-verified immutable bytes."""
    validate_ticket(handoff)
    if not isinstance(saved, dict) or set(saved) != {'task_id', 'source_sha256', 'checkpoint', 'sha256'}:
        raise ValueError('invalid durable checkpoint manifest')
    if (saved['task_id'] != handoff['task_id'] or saved['source_sha256'] != handoff['source_sha256']
            or type(saved['checkpoint']) is not int or saved['checkpoint'] != handoff['checkpoint']
            or not _sha(saved['sha256']) or not isinstance(blob, bytes)
            or (handoff['checkpoint_sha256'] is not None and
                saved['sha256'] != handoff['checkpoint_sha256'])
            or len(blob) > 8_000_000 or hashlib.sha256(blob).hexdigest() != saved['sha256']):
        raise ValueError('checkpoint bytes/identity not verified')
    return saved['checkpoint']


def receipt(handoff, status, output, checkpoint):
    """Audit envelope only; not yet a canonical v1/v2 Issue completion."""
    validate_ticket(handoff)
    if status not in ('SUCCEEDED', 'FAILED', 'BLOCKED_SOURCE'):
        raise ValueError('invalid result status')
    if (type(checkpoint) is not int or checkpoint < handoff['checkpoint']
            or checkpoint > 10000 or not isinstance(output, bytes) or len(output) > 500000):
        raise ValueError('unbounded/invalid output')
    digest = hashlib.sha256(output).hexdigest() if output else None
    result = dict(ticket=handoff, status=status, checkpoint=checkpoint,
                  output_sha256=digest, result_sha256=None)
    canonical = json.dumps({k: v for k, v in result.items() if k != 'result_sha256'},
                           sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    result['result_sha256'] = hashlib.sha256(canonical).hexdigest()
    return result


def verify_receipt(result, handoff, output):
    if not isinstance(result, dict) or set(result) != {'ticket', 'status', 'checkpoint', 'output_sha256', 'result_sha256'}:
        raise ValueError('invalid receipt envelope')
    validate_ticket(handoff)
    if result['ticket'] != handoff:
        raise ValueError('cross-worker receipt replay')
    expected = receipt(handoff, result['status'], output, result['checkpoint'])
    if result != expected:
        raise ValueError('receipt digest mismatch')
    return True
