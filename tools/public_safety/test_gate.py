"""Publication gate behavior tests; synthetic credentials only."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from gate import PublicationGate


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@' + 'example.invalid')
        self.git('config', 'user.name', 'Fixture')
        self.git('remote', 'add', 'origin',
                 'https://github.com/moaz76943-creator/-offline-packs-store.git')
        self.write('README.md', b'public repository')
        self.git('add', 'README.md')
        self.git('commit', '-qm', 'baseline')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True,
                              capture_output=True).stdout

    def write(self, path, contents):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)

    def stage(self, path, contents):
        self.write(path, contents)
        self.git('add', '--', path)

    def scan(self, **kwargs):
        return PublicationGate(self.root, **kwargs).scan()

    def test_clean_document_passes(self):
        self.stage('docs/guide.md', b'Approved public documentation.\n')
        self.assertEqual(self.scan().state, 'PASS')

    def test_empty_stage_blocked(self):
        self.assertEqual(self.scan().state, 'BLOCKED')

    def test_wrong_remote_blocked(self):
        self.git('remote', 'set-url', 'origin', 'https://github.com/example/other.git')
        self.stage('docs/guide.md', b'harmless')
        self.assertEqual(self.scan().state, 'BLOCKED')

    def test_fake_github_token_rejected_without_raw_leak(self):
        fake = 'ghp_' + 'F' * 36
        self.stage('docs/notes.md', ('token=' + fake).encode())
        result = self.scan()
        self.assertEqual(result.state, 'FAIL')
        self.assertNotIn(fake, result.public_report())
        self.assertNotIn('docs/notes.md', result.public_report())

    def test_private_key_rejected_without_value(self):
        fake = '-----BEGIN ' + 'PRIVATE KEY-----\nFAKE\n'
        self.stage('docs/example.md', fake.encode())
        self.assertEqual(self.scan().state, 'FAIL')

    def test_rejects_forbidden_suffixes_and_private_paths(self):
        for path in ('packs/learner.sqlite', 'images/signing.jks',
                     'docs/.env', 'lib/' + 'services/core.dart',
                     'docs/secret.log'):
            with self.subTest(path=path):
                self.stage(path, b'opaque')
                self.assertEqual(self.scan().state, 'FAIL')
                self.git('reset', '-q', '--', path)

    def test_rejects_unapproved_archive_and_archive_traversal(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('../secret.env', 'not-a-real-secret')
        self.stage('media/payload.zip', buffer.getvalue())
        self.assertEqual(self.scan().state, 'FAIL')

    def test_rejects_unsigned_pack_and_binary_snapshot(self):
        self.stage('packs/de_new.pack.gz', gzip.compress(b'{}'))
        self.assertEqual(self.scan().state, 'BLOCKED')
        self.git('reset', '-q', '--', 'packs/de_new.pack.gz')
        self.stage('docs/raw.bin', b'\x00\x01\x02\x03')
        self.assertEqual(self.scan().state, 'FAIL')

    def test_licensed_pack_with_integrity_is_accepted(self):
        path = 'packs/de_new.pack.gz'
        payload = gzip.compress(b'{"languageCode":"de","entries":[]}')
        digest = hashlib.sha256(payload).hexdigest()
        self.stage(path, payload)
        self.stage('manifest.json', json.dumps({'languages': [
            {'pack_file': 'de_new.pack.gz', 'sha256': digest}]}).encode())
        ledger = {'exports': {path: {
            'sha256': digest, 'license': 'CC0-1.0',
            'source': 'https://example.invalid/dataset',
            'rights_holder': 'Synthetic fixture author',
            'attribution': 'Synthetic fixture'}}}
        self.stage('tools/public_safety/provenance.json', json.dumps(ledger).encode())
        self.assertEqual(self.scan().state, 'PASS')

    def test_bad_manifest_hash_rejected(self):
        path = 'packs/de_new.pack.gz'
        payload = gzip.compress(b'{}')
        digest = hashlib.sha256(payload).hexdigest()
        self.stage(path, payload)
        self.stage('manifest.json', json.dumps({'languages': [
            {'pack_file': 'de_new.pack.gz', 'sha256': '0' * 64}]}).encode())
        self.stage('tools/public_safety/provenance.json', json.dumps({
            'exports': {path: {'sha256': digest, 'license': 'CC0-1.0',
                               'source': 'https://example.invalid/fixture',
                               'rights_holder': 'Test', 'attribution': 'Test'}}}).encode())
        self.assertEqual(self.scan().state, 'FAIL')

    def test_pii_fields_rejected(self):
        self.stage('catalog/snapshot.json', b'{"user_id":"fictional-user"}')
        self.assertEqual(self.scan().state, 'FAIL')

    def test_history_flags_bad_previous_path_without_revealing_it(self):
        self.stage('docs/private.key', b'fake')
        self.git('commit', '-qm', 'synthetic old leak')
        self.stage('docs/good.md', b'good')
        r = self.scan(check_history=True)
        self.assertEqual(r.state, 'FAIL')
        self.assertIn('HISTORY_REVIEW', r.public_report())
        self.assertNotIn('private.key', r.public_report())

    def test_staged_blob_not_worktree_is_scanned(self):
        self.stage('docs/guide.md', b'clean staged')
        self.write('docs/guide.md', ('ghp_' + 'X' * 36).encode())
        self.assertEqual(self.scan().state, 'PASS')

    def test_symlink_rejected(self):
        link = self.root / 'docs' / 'link.md'
        link.parent.mkdir(exist_ok=True)
        link.symlink_to('/tmp/fixture')
        self.git('add', '--', 'docs/link.md')
        self.assertEqual(self.scan().state, 'FAIL')


if __name__ == '__main__':
    unittest.main()
