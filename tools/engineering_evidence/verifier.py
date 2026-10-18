"""Read-only, fail-closed PR/CI evidence verifier. Never a release approval gate."""
import hashlib
import json
import re
import selectors
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import quote

REPO_RE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
SHA_RE = re.compile(r'^[0-9a-f]{40}$')
DIGEST_RE = re.compile(r'^sha256:([0-9a-f]{64})$')
MAX_FILES = 3000
MAX_RUNS = 100
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


class EvidenceError(ValueError):
    pass


class GhReader:
    """GitHub CLI transport; GET only, fixed argv, bounded calls, no token in output."""

    def get(self, path):
        try:
            result = subprocess.run(['gh', 'api', '--method', 'GET', path],
                                    check=True, capture_output=True, timeout=25)
            if len(result.stdout) > 4 * 1024 * 1024:
                raise EvidenceError('API_RESPONSE_TOO_LARGE')
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, ValueError) as exc:
            raise EvidenceError('GITHUB_READ_FAILED') from exc

    def digest(self, repo, artifact_id, max_bytes=MAX_ARTIFACT_BYTES):
        """Hash actual downloaded archive bytes, stopping at the declared size ceiling."""
        cmd = ['gh', 'api', '--method', 'GET',
               f'repos/{repo}/actions/artifacts/{artifact_id}/zip']
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise EvidenceError('ARTIFACT_DOWNLOAD_FAILED') from exc
        digest = hashlib.sha256()
        total = 0
        poll = selectors.DefaultSelector()
        try:
            poll.register(proc.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 45
            while True:
                remain = deadline - time.monotonic()
                if remain <= 0 or not poll.select(remain):
                    raise EvidenceError('ARTIFACT_DOWNLOAD_TIMEOUT')
                chunk = proc.stdout.read1(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise EvidenceError('ARTIFACT_TOO_LARGE')
                digest.update(chunk)
            if proc.wait(timeout=3) != 0 or total == 0:
                raise EvidenceError('ARTIFACT_DOWNLOAD_FAILED')
            return digest.hexdigest()
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise EvidenceError('ARTIFACT_DOWNLOAD_FAILED') from exc
        finally:
            poll.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()


def _sha(value):
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def _id(value):
    return type(value) is int and value > 0


def _branch_head(client, repo, branch):
    value = client.get(f'repos/{repo}/branches/{quote(branch, safe="")}')
    sha = value.get('commit', {}).get('sha')
    if not _sha(sha):
        raise EvidenceError('INVALID_BRANCH_SHA')
    return sha


def _files(client, repo, number, expected):
    if type(expected) is not int or expected < 0 or expected > MAX_FILES:
        raise EvidenceError('INVALID_CHANGED_FILE_COUNT')
    found = []
    for page in range(1, 32):
        block = client.get(f'repos/{repo}/pulls/{number}/files?per_page=100&page={page}')
        if not isinstance(block, list) or len(block) > 100:
            raise EvidenceError('INVALID_FILE_LIST')
        for item in block:
            name = item.get('filename') if isinstance(item, dict) else None
            if not isinstance(name, str) or not name or name.startswith('/') or '..' in name.split('/'):
                raise EvidenceError('INVALID_FILE_PATH')
            found.append(name)
        if len(block) < 100:
            break
    if len(found) != expected or len(found) != len(set(found)):
        raise EvidenceError('INCOMPLETE_PR_FILE_LIST')
    return sorted(found)


def verify(client, repo, number, task_id, owner, *, verify_artifacts=False,
           private_links=(), timestamp=None):
    """Use only actual REST objects; metadata/comments cannot assert CI success."""
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo) or '..' in repo:
        raise EvidenceError('INVALID_REPOSITORY')
    if not _id(number) or not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 128:
        raise EvidenceError('INVALID_TASK')
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
        raise EvidenceError('INVALID_OWNER')
    pr_path = f'repos/{repo}/pulls/{number}'
    pr = client.get(pr_path)
    if not isinstance(pr, dict) or pr.get('number') != number:
        raise EvidenceError('PR_ID_MISMATCH')
    base = pr.get('base') or {}
    head = pr.get('head') or {}
    branch = base.get('ref')
    base_sha = base.get('sha')
    head_sha = head.get('sha')
    if (base.get('repo', {}).get('full_name') != repo or not isinstance(branch, str)
            or not branch or not _sha(base_sha) or not _sha(head_sha)):
        raise EvidenceError('INVALID_PR_IDENTITY')
    start_sha = _branch_head(client, repo, branch)
    reasons = []
    if start_sha != base_sha:
        reasons.append('STALE_PR_BASE')
    try:
        files = _files(client, repo, number, pr.get('changed_files'))
    except EvidenceError as exc:
        files = []
        reasons.append(str(exc))
    runs_payload = client.get(f'repos/{repo}/actions/runs?head_sha={head_sha}&per_page=100&page=1')
    if not isinstance(runs_payload, dict) or not isinstance(runs_payload.get('workflow_runs'), list):
        raise EvidenceError('INVALID_WORKFLOW_RUN_LIST')
    raw = runs_payload['workflow_runs']
    if len(raw) > MAX_RUNS or runs_payload.get('total_count', len(raw)) > MAX_RUNS:
        reasons.append('INCOMPLETE_RUN_PAGINATION')
    related = [r for r in raw if isinstance(r, dict) and r.get('head_sha') == head_sha
               and r.get('event') == 'pull_request'
               and any(isinstance(p, dict) and p.get('number') == number
                       for p in (r.get('pull_requests') or []))]
    selected = {}
    for run in related:
        if not _id(run.get('id')) or not _id(run.get('run_attempt')):
            reasons.append('INVALID_RUN_IDENTITY')
            continue
        name = run.get('name') or str(run.get('workflow_id') or '')
        if not name:
            reasons.append('UNKNOWN_WORKFLOW_NAME')
            continue
        old = selected.get(name)
        if old is None or (run['id'], run['run_attempt']) > (old['id'], old['run_attempt']):
            selected[name] = run
    actual_runs = sorted(selected.values(), key=lambda r: (r['id'], r['run_attempt']))
    ci = []
    artifacts = []
    any_fail = False
    pending = False
    for run in actual_runs:
        status, conclusion = run.get('status'), run.get('conclusion')
        ci.append({'run_id': run['id'], 'run_attempt': run['run_attempt'],
                   'workflow': run.get('name'), 'status': status, 'conclusion': conclusion,
                   'head_sha': head_sha,
                   'url': f'https://github.com/{repo}/actions/runs/{run["id"]}'})
        if status != 'completed':
            pending = True
        elif conclusion == 'failure' or conclusion in ('timed_out', 'action_required'):
            any_fail = True
        elif conclusion != 'success':
            reasons.append('NON_SUCCESSFUL_WORKFLOW')
        if status == 'completed' and conclusion == 'success':
            response = client.get(f'repos/{repo}/actions/runs/{run["id"]}/artifacts?per_page=100')
            records = response.get('artifacts') if isinstance(response, dict) else None
            if not isinstance(records, list) or len(records) != response.get('total_count', len(records)):
                reasons.append('INCOMPLETE_ARTIFACT_LIST')
                continue
            for art in records:
                if not isinstance(art, dict) or not _id(art.get('id')):
                    reasons.append('INVALID_ARTIFACT_RECORD')
                    continue
                claimed = art.get('digest')
                match = DIGEST_RE.fullmatch(claimed) if isinstance(claimed, str) else None
                actual = None
                if art.get('expired') or not match:
                    reasons.append('ARTIFACT_DIGEST_UNAVAILABLE')
                elif not verify_artifacts:
                    reasons.append('ARTIFACT_BYTES_NOT_VERIFIED')
                else:
                    try:
                        actual = client.digest(repo, art['id'], MAX_ARTIFACT_BYTES)
                        if actual != match.group(1):
                            reasons.append('ARTIFACT_SHA256_MISMATCH')
                    except EvidenceError as exc:
                        reasons.append(str(exc))
                artifacts.append({'artifact_id': art['id'], 'run_id': run['id'],
                                  'sha256': actual if actual == (match.group(1) if match else None) else None})
    checks_response = client.get(f'repos/{repo}/commits/{head_sha}/check-runs?per_page=100')
    checks = checks_response.get('check_runs') if isinstance(checks_response, dict) else None
    if not isinstance(checks, list) or checks_response.get('total_count', len(checks)) > len(checks):
        reasons.append('INCOMPLETE_CHECK_RUNS')
        checks = []
    for check in checks:
        if check.get('head_sha') != head_sha:
            reasons.append('STALE_CHECK_SHA')
        elif check.get('status') != 'completed':
            pending = True
        elif check.get('conclusion') == 'failure':
            any_fail = True
        elif check.get('conclusion') not in ('success', 'neutral'):
            reasons.append('NON_SUCCESSFUL_CHECK')
    final_pr = client.get(pr_path)
    end_sha = _branch_head(client, repo, branch)
    if (end_sha != start_sha or final_pr.get('head', {}).get('sha') != head_sha
            or final_pr.get('base', {}).get('sha') != base_sha):
        reasons.append('HEAD_CHANGED_DURING_VERIFICATION')
    if 'HEAD_CHANGED_DURING_VERIFICATION' in reasons or 'STALE_PR_BASE' in reasons or 'STALE_CHECK_SHA' in reasons:
        state = 'STALE_EVIDENCE'
    elif any_fail:
        state = 'FAIL'
    elif reasons or pending:
        state = 'BLOCKED'
    elif not actual_runs:
        state = 'NOT_RUN'
    else:
        state = 'VERIFIED'
    refs = []
    for link in private_links:
        if not isinstance(link, str) or not link.startswith('https://github.com/') or len(link) > 2048:
            raise EvidenceError('INVALID_PRIVATE_REFERENCE')
        refs.append({'url': link, 'url_sha256': hashlib.sha256(link.encode()).hexdigest()})
    digests = [a['sha256'] for a in artifacts if a['sha256']]
    return {'schema_version': '1.0', 'task_id': task_id, 'repository': repo,
            'base_branch': branch, 'base_head_sha': start_sha, 'pr_head_sha': head_sha,
            'pr_number': number, 'pr_url': f'https://github.com/{repo}/pull/{number}',
            'agent_owner': owner, 'changed_files': files, 'test_commands': [],
            'test_results': ci, 'ci_runs': ci,
            'ci_run_id': ci[-1]['run_id'] if ci else None,
            'ci_run_attempt': ci[-1]['run_attempt'] if ci else None,
            'artifact_sha256': digests[0] if len(digests) == 1 else None,
            'artifacts': artifacts, 'private_evidence': refs,
            'execution_timestamp': timestamp or datetime.now(timezone.utc).isoformat(),
            'final_status': state, 'reasons': sorted(set(reasons)),
            'publication_approved': False, 'merge_authorized': False,
            'command_execution_independently_verified': False}


def markdown(report):
    return ('# Engineering task evidence\n\n'
            f"- Task: \u0060{report['task_id']}\u0060\n"
            f"- Repository: \u0060{report['repository']}\u0060\n"
            f"- PR: {report['pr_url']}\n"
            f"- Base HEAD: \u0060{report['base_head_sha']}\u0060\n"
            f"- PR HEAD: \u0060{report['pr_head_sha']}\u0060\n"
            f"- Status: **{report['final_status']}**\n"
            f"- CI run: \u0060{report['ci_run_id']}\u0060 / attempt \u0060{report['ci_run_attempt']}\u0060\n"
            f"- Reason codes: \u0060{', '.join(report['reasons']) or 'NONE'}\u0060\n\n"
            'Read-only CI evidence; not approval for merging or publishing.\n')
