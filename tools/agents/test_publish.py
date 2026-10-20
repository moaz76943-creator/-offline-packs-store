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


if __name__ == '__main__':
    unittest.main()
