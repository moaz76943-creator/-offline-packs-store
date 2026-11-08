"""Local-git regressions for agent checkpoint isolation; no GitHub network."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def git(cwd, *args):
    result = subprocess.run(['git', *args], cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(f"git {' '.join(args)}: {result.stderr}")
    return result.stdout.strip()


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root / 'remote.git'
        git(self.root, 'init', '--bare', '--initial-branch=main', str(self.remote))
        seed = self.root / 'seed'
        git(self.root, 'clone', str(self.remote), str(seed))
        git(seed, 'config', 'user.email', 'test@invalid.example')
        git(seed, 'config', 'user.name', 'Test')
        (seed / 'STATUS.md').write_text('main status\n')
        (seed / 'README.md').write_text('main\n')
        git(seed, 'add', '.')
        git(seed, 'commit', '-m', 'main')
        git(seed, 'push', 'origin', 'HEAD:refs/heads/main')
        git(seed, 'switch', '-c', 'agents/data')
        (seed / 'STATUS.md').write_text('agent status\n')
        path = seed / 'state/agents/watchdog.json'
        path.parent.mkdir(parents=True)
        path.write_text('{"status":"ok"}\n')
        src = seed / 'data/agents/harvest/tatoeba/sv/sentences.json'
        src.parent.mkdir(parents=True)
        src.write_text('{"rows": [1]}\n')
        git(seed, 'add', '.')
        git(seed, 'commit', '-m', 'snapshot')
        git(seed, 'push', 'origin', 'HEAD:refs/heads/agents/data')

    def worker(self, name):
        work = self.root / name
        git(self.root, 'clone', '--branch', 'main', str(self.remote), str(work))
        git(work, 'config', 'user.email', 'test@invalid.example')
        git(work, 'config', 'user.name', 'Test')
        # Snapshot files absent from main previously prevented publish checkout.
        subprocess.run(
            ['bash', str(SCRIPTS / 'prepare.sh')], cwd=work, check=True,
            capture_output=True, text=True,
        )
        self.assertEqual(git(work, 'diff', '--cached', '--name-only'), '')
        return work

    def result_dir(self, name):
        out = self.root / (name + '-out')
        path = out / f'state/agents/{name}.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'status': 'ok', 'name': name}))
        target = out / f'data/agents/harvest/{name}/en/grammar.json'
        target.parent.mkdir(parents=True)
        target.write_text('{"rows": ["evidence"]}\n')
        return out

    def publish(self, worker, name):
        env = dict(os.environ, AGENT_OUT=str(self.root / (name + '-out')))
        return subprocess.run(
            ['bash', str(SCRIPTS / 'publish.sh'), name],
            cwd=worker, env=env, text=True, capture_output=True,
        )

    def test_dirty_main_snapshot_publishes_only_agent_outputs(self):
        work = self.worker('worker')
        self.result_dir('ud')
        result = self.publish(work, 'ud')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(work, 'branch', '--show-current'), 'main')
        self.assertEqual(git(work, 'diff', '--cached', '--name-only'), '')
        observer = self.root / 'observer'
        git(self.root, 'clone', '--branch', 'agents/data', str(self.remote), str(observer))
        self.assertTrue((observer / 'state/agents/ud.json').exists())
        self.assertTrue((observer / 'state/agents/watchdog.json').exists())
        self.assertEqual((observer / 'STATUS.md').read_text(), 'agent status\n')
        self.assertTrue((observer / 'data/agents/harvest/tatoeba/sv/sentences.json').exists())
        self.assertTrue((observer / 'data/agents/harvest/ud/en/grammar.json').exists())
        old_sha = git(observer, 'rev-parse', 'HEAD')
        again = self.publish(work, 'ud')
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        git(observer, 'pull', '--ff-only')
        self.assertEqual(git(observer, 'rev-parse', 'HEAD'), old_sha)

    def test_one_retry_merges_concurrent_disjoint_agent_commits(self):
        work_a = self.worker('worker-a')
        work_b = self.worker('worker-b')
        self.result_dir('alpha')
        self.result_dir('beta')
        marker = self.root / 'marker'
        hook = work_a / '.git/hooks/pre-push'
        hook.write_text(f'''#!/bin/sh
if [ ! -f "{marker}" ]; then
 touch "{marker}"
 cd "{work_b}" || exit 1
 unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE
 AGENT_OUT="{self.root / 'beta-out'}" bash "{SCRIPTS / 'publish.sh'}" beta || exit 1
fi
''')
        hook.chmod(0o755)
        res = self.publish(work_a, 'alpha')
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        observer = self.root / 'after-concurrent'
        git(self.root, 'clone', '--branch', 'agents/data', str(self.remote), str(observer))
        self.assertTrue((observer / 'state/agents/alpha.json').exists())
        self.assertTrue((observer / 'state/agents/beta.json').exists())
        self.assertTrue((observer / 'state/agents/watchdog.json').exists())
        self.assertEqual(
            git(observer, 'log', '--oneline', '--grep=checkpoint').count('checkpoint'), 2,
        )

    def _record_pointer(self, sha):
        main = self.root / 'main-pointer'
        git(self.root, 'clone', '--branch', 'main', str(self.remote), str(main))
        git(main, 'config', 'user.email', 'test@invalid.example')
        git(main, 'config', 'user.name', 'Test')
        pointer = main / 'state/agents/snapshot-ref.json'
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(json.dumps({
            'schema_version': '1.0.0',
            'branch': 'agents/data',
            'sha': sha,
        }) + '\n')
        git(main, 'add', 'state/agents/snapshot-ref.json')
        git(main, 'commit', '-m', 'record snapshot sha')
        git(main, 'push', 'origin', 'HEAD:refs/heads/main')
        git(self.remote, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
        return sha

    def test_missing_branch_recreates_from_recorded_sha(self):
        sha = git(self.remote, 'rev-parse', 'refs/heads/agents/data')
        self._record_pointer(sha)
        git(self.root / 'main-pointer', 'push', 'origin', '--delete', 'agents/data')
        self.assertNotIn('agents/data', git(self.remote, 'show-ref'))
        work = self.worker('recover')
        self.assertTrue((work / 'state/agents/watchdog.json').is_file())
        self.assertEqual(
            json.loads((work / 'state/agents/snapshot-ref.json').read_text())['sha'],
            sha,
        )
        self.result_dir('recover')
        result = self.publish(work, 'recover')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        tip = git(self.remote, 'rev-parse', 'refs/heads/agents/data')
        self.assertNotEqual(tip, sha)
        self.assertEqual(git(self.remote, 'rev-parse', tip + '^'), sha)
        observer = self.root / 'recovered'
        git(self.root, 'clone', '--branch', 'agents/data', str(self.remote), str(observer))
        self.assertTrue((observer / 'state/agents/watchdog.json').is_file())
        self.assertTrue((observer / 'state/agents/recover.json').is_file())

    def test_missing_branch_without_sha_skips_without_a_new_root(self):
        git(self.root / 'seed', 'push', 'origin', '--delete', 'agents/data')
        work = self.root / 'skip'
        git(self.root, 'clone', '--branch', 'main', str(self.remote), str(work))
        git(work, 'config', 'user.email', 'test@invalid.example')
        git(work, 'config', 'user.name', 'Test')
        prepared = subprocess.run(
            ['bash', str(SCRIPTS / 'prepare.sh')], cwd=work, check=False,
            capture_output=True, text=True,
        )
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        self.assertFalse((work / 'state/agents/watchdog.json').exists())
        self.result_dir('skip')
        published = self.publish(work, 'skip')
        self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
        self.assertNotIn('agents/data', git(self.remote, 'show-ref'))
        self.assertIn('skipping publish', published.stdout + published.stderr)

    def test_recorded_sha_does_not_rewind_a_newer_branch(self):
        old = git(self.remote, 'rev-parse', 'refs/heads/agents/data')
        newer = self.root / 'newer'
        git(self.root, 'clone', '--branch', 'agents/data', str(self.remote), str(newer))
        git(newer, 'config', 'user.email', 'test@invalid.example')
        git(newer, 'config', 'user.name', 'Test')
        marker = newer / 'state/agents/newer.json'
        marker.write_text('{"status":"newer"}\n')
        git(newer, 'add', 'state/agents/newer.json')
        git(newer, 'commit', '-m', 'newer snapshot')
        git(newer, 'push', 'origin', 'HEAD:refs/heads/agents/data')
        new = git(self.remote, 'rev-parse', 'refs/heads/agents/data')
        self.assertNotEqual(new, old)
        self._record_pointer(old)
        work = self.worker('keep-new')
        self.assertTrue((work / 'state/agents/newer.json').is_file())
        self.result_dir('keep-new')
        result = self.publish(work, 'keep-new')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        tip = git(self.remote, 'rev-parse', 'refs/heads/agents/data')
        self.assertNotEqual(tip, old)
        self.assertEqual(git(self.remote, 'rev-parse', tip + '^'), new)


if __name__ == '__main__':
    unittest.main()
