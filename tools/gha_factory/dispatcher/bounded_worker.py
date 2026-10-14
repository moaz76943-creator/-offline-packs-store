"""Bound an existing dispatcher worker in a killable subprocess group.

This is a transport safety wrapper, NOT a new public task type or queue engine.
It preserves the queue-v1 receipt/checkpoint contract and never publishes content.
"""
import json
import os
import signal
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from . import queue, controller

MAX_SECONDS = 600
ROOT = Path(__file__).resolve().parents[3]


def _failure(task, run_id, attempt, error):
    return {'schema_version': queue.VERSION, 'task_id': task['task_id'],
            'run_id': run_id, 'run_attempt': attempt, 'status': 'FAILED',
            'checkpoint': task['checkpoint'], 'candidate_count': 0,
            'candidate_sha256': None, 'error_code': error}


def _write(directory, receipt):
    temp = directory / 'receipt.tmp'
    temp.write_text(json.dumps(receipt, sort_keys=True, separators=(',', ':'),
                               allow_nan=False), encoding='utf-8')
    temp.replace(directory / 'receipt.json')


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate receipt field')
        result[key] = value
    return result


def _verified_receipt(path, task, run_id, attempt, returncode):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError('missing, unsafe or oversized receipt')
    receipt = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_no_duplicate_keys)
    if (not isinstance(receipt, dict) or receipt.get('task_id') != task['task_id']
            or receipt.get('run_id') != run_id or receipt.get('run_attempt') != attempt):
        raise ValueError('receipt identity mismatch')
    # Reuse the canonical v1 state transition validator; no new receipt contract.
    queue.finalize(task, receipt, queue.utc_now())
    if (returncode == 0) != (receipt['status'] in ('SUCCEEDED', 'BLOCKED_SOURCE')):
        raise ValueError('worker exit/receipt status disagreement')
    return receipt


def execute(api, number, task_id, run_id, attempt, directory, timeout=MAX_SECONDS):
    """Launch a fixed worker command; on timeout, preserve old checkpoint for retry."""
    if type(timeout) is not int or not 1 <= timeout <= MAX_SECONDS:
        raise ValueError('invalid bounded worker timeout')
    if type(number) is not int or number <= 0 or not queue.HEX.fullmatch(str(task_id)):
        raise ValueError('invalid issue/task identity')
    issue = api.one(number)
    owns_issue = getattr(controller, 'owned_queue_issue', None)
    if owns_issue is not None:
        trusted = owns_issue(issue)
    else:
        trusted = (isinstance(issue, dict) and 'pull_request' not in issue
                   and isinstance(issue.get('title'), str)
                   and issue['title'].startswith(queue.PREFIX)
                   and (issue.get('user') or {}).get('login') == controller.OWNER)
    if not trusted:
        raise ValueError('untrusted issue owner')
    task = queue.parse(issue.get('body'))
    if (task['task_id'] != task_id or task['state'] != 'CLAIMED'
            or task['run_id'] != run_id or task['run_attempt'] != attempt
            or task['lease_until'] is None
            or queue.date_value(task['lease_until']) <= queue.utc_now() + timedelta(seconds=timeout + 30)):
        raise ValueError('expired or mismatched worker lease')

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink() or (directory / 'receipt.json').exists() or (directory / 'receipt.json').is_symlink():
        raise ValueError('stale or unsafe worker output')
    argv = [sys.executable, str(Path(__file__).with_name('cli.py')),
            'worker-exec', '--issue', str(number), '--task-id', task_id,
            '--out', str(directory.resolve())]
    timed_out = False
    try:
        proc = subprocess.Popen(argv, cwd=ROOT, start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            code = -1
    except OSError:
        code = -1

    if timed_out:
        receipt = _failure(task, run_id, attempt, 'TIMEOUT')
    else:
        try:
            receipt = _verified_receipt(directory / 'receipt.json', task, run_id, attempt, code)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError):
            receipt = _failure(task, run_id, attempt, 'INVALID_INPUT' if code == 0 else 'EXECUTION')
    if receipt['status'] == 'FAILED' and (timed_out or not (directory/'receipt.json').is_file()
                                         or receipt['error_code'] in ('INVALID_INPUT', 'EXECUTION')):
        _write(directory, receipt)
    return receipt
