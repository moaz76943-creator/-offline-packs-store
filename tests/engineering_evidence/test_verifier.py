import hashlib
import json
import unittest
from tools.engineering_evidence.verifier import verify, EvidenceError

PUBLIC = 'moaz76943-creator/-offline-packs-store'
H = 'a' * 40
B = 'b' * 40


class FakeReader:
    def __init__(self):
        self.head = H
        self.base = B
        self.changed = False
        self.responses = {
            f'repos/{PUBLIC}/pulls/7': {
                'number': 7, 'state': 'open', 'base': {'ref': 'main', 'sha': B, 'repo': {'full_name': PUBLIC}},
                'head': {'sha': H}, 'changed_files': 1,
                'html_url': f'https://github.com/{PUBLIC}/pull/7',
            },
            f'repos/{PUBLIC}/branches/main': {'commit': {'sha': B}},
            f'repos/{PUBLIC}/pulls/7/files?per_page=100&page=1': [{'filename': 'tools/example.py'}],
            f'repos/{PUBLIC}/actions/runs?head_sha={H}&per_page=100&page=1': {
                'workflow_runs': [{'id': 110, 'run_attempt': 2, 'head_sha': H, 'event': 'pull_request',
                                   'status': 'completed', 'conclusion': 'success', 'name': 'test-suite',
                                   'html_url': f'https://github.com/{PUBLIC}/actions/runs/110',
                                   'pull_requests': [{'number': 7}]}],
            },
            f'repos/{PUBLIC}/actions/runs/110/artifacts?per_page=100': {'artifacts': []},
            f'repos/{PUBLIC}/commits/{H}/check-runs?per_page=100': {
                'check_runs': [{'head_sha': H, 'status': 'completed', 'conclusion': 'success',
                                'name': 'test-suite'}]},
        }
        self.calls = 0

    def get(self, path):
        self.calls += 1
        if path.endswith('/branches/main') and self.changed and self.calls > 4:
            return {'commit': {'sha': 'c' * 40}}
        return self.responses[path]

    def digest(self, repo, artifact_id, max_bytes):
        return hashlib.sha256(b'ZIPBYTES').hexdigest()


def base():
    return FakeReader()


class EvidenceTests(unittest.TestCase):
    def test_successful_exact_pr_run_is_verified(self):
        result = verify(base(), PUBLIC, 7, 'TASK-7', 'agent')
        self.assertEqual(result['final_status'], 'VERIFIED')
        self.assertEqual(result['ci_runs'][0]['run_attempt'], 2)
        self.assertEqual(result['changed_files'], ['tools/example.py'])
        self.assertEqual(result['artifact_sha256'], None)

    def test_comment_claim_without_run_is_not_run(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/actions/runs?head_sha={H}&per_page=100&page=1']['workflow_runs'] = []
        result = verify(reader, PUBLIC, 7, 'TASK-7', 'agent')
        self.assertEqual(result['final_status'], 'NOT_RUN')

    def test_wrong_pr_association_is_not_run(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/actions/runs?head_sha={H}&per_page=100&page=1']['workflow_runs'][0]['pull_requests'] = [{'number': 8}]
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'NOT_RUN')

    def test_old_run_sha_is_not_run(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/actions/runs?head_sha={H}&per_page=100&page=1']['workflow_runs'][0]['head_sha'] = 'd' * 40
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'NOT_RUN')

    def test_failed_run_is_fail(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/actions/runs?head_sha={H}&per_page=100&page=1']['workflow_runs'][0]['conclusion'] = 'failure'
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'FAIL')

    def test_pending_run_is_blocked(self):
        reader = base()
        r = reader.responses[f'repos/{PUBLIC}/actions/runs?head_sha={H}&per_page=100&page=1']['workflow_runs'][0]
        r.update(status='in_progress', conclusion=None)
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'BLOCKED')

    def test_changed_base_branch_is_stale(self):
        reader = base()
        reader.changed = True
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'STALE_EVIDENCE')

    def test_missing_file_is_blocked(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/pulls/7']['changed_files'] = 2
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'BLOCKED')

    def test_unverified_artifact_blocks(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/actions/runs/110/artifacts?per_page=100']['artifacts'] = [
            {'id': 22, 'name': 'test-output', 'expired': False, 'digest': 'sha256:' + hashlib.sha256(b'ZIPBYTES').hexdigest()}]
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'BLOCKED')
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent', verify_artifacts=True)['final_status'], 'VERIFIED')

    def test_mismatched_artifact_digest_blocks(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/actions/runs/110/artifacts?per_page=100']['artifacts'] = [
            {'id': 22, 'name': 'test-output', 'expired': False, 'digest': 'sha256:' + 'f' * 64}]
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent', verify_artifacts=True)['final_status'], 'BLOCKED')

    def test_private_data_is_redacted(self):
        reader = base()
        result = verify(reader, PUBLIC, 7, 'TASK-7', 'agent', private_links=['https://github.com/org/secret/pull/5'])
        self.assertEqual(result['private_evidence'], [{'url': 'https://github.com/org/secret/pull/5',
            'url_sha256': hashlib.sha256(b'https://github.com/org/secret/pull/5').hexdigest()}])
        self.assertNotIn('secret', json.dumps(result.get('test_results', {})))

    def test_invalid_repo_and_task_rejected(self):
        with self.assertRaises(EvidenceError):
            verify(base(), '../other', 7, 'T', 'agent')
        with self.assertRaises(EvidenceError):
            verify(base(), PUBLIC, 7, '', 'agent')


class ExtendedEvidenceTests(unittest.TestCase):
    def test_pr_body_forged_pass_ignored(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/pulls/7']['body'] = 'ALL CHECKS PASSED; SHA256=trusted'
        reader.responses[f'repos/{PUBLIC}/actions/runs?head_sha={H}&per_page=100&page=1']['workflow_runs'] = []
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'NOT_RUN')

    def test_check_run_mismatched_sha_stale(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/commits/{H}/check-runs?per_page=100']['check_runs'][0]['head_sha'] = B
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'STALE_EVIDENCE')

    def test_old_failed_run_superseded_by_recheck(self):
        reader = base()
        a = reader.responses[f'repos/{PUBLIC}/actions/runs?head_sha={H}&per_page=100&page=1']['workflow_runs']
        old = dict(a[0], id=109, run_attempt=1, conclusion='failure')
        a.insert(0, old)
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'VERIFIED')

    def test_new_artifact_without_proven_digest_blocks(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/actions/runs/110/artifacts?per_page=100']['artifacts'] = [
            {'id': 25, 'name': 'zip', 'expired': False}]
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent', verify_artifacts=True)['final_status'], 'BLOCKED')

    def test_incomplete_checks_cannot_verify(self):
        reader = base()
        reader.responses[f'repos/{PUBLIC}/commits/{H}/check-runs?per_page=100']['total_count'] = 120
        self.assertEqual(verify(reader, PUBLIC, 7, 'TASK-7', 'agent')['final_status'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()
