"""Offline candidate staging tests; mocked inspector is not a real rights approval."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch
from tools.release_publication import staging as s

class StageTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name).resolve()
        (self.root/'packs').mkdir()
        self.data=gzip.compress(b'{"fixture":true}',mtime=0)
        (self.root/'packs/x.pack.gz').write_bytes(self.data)
        self.sha=hashlib.sha256(self.data).hexdigest()

    def simulated_checker(self,fixture=False,approved=False):
        first=ModuleType('tools.gha_factory');first.__path__=[]
        second=ModuleType('tools.gha_factory.pack_conformance');second.__path__=[]
        last=ModuleType('tools.gha_factory.pack_conformance.check')
        last.inspect=lambda *args,**kw:{'fixture_only':fixture,'publication_approved':approved,
            'archive_sha256':self.sha,'sqlite_sha256':'b'*64,'source_ids':['test-source']}
        return patch.dict(sys.modules,{'tools.gha_factory':first,
            'tools.gha_factory.pack_conformance':second,
            'tools.gha_factory.pack_conformance.check':last})

    def stage(self,path='packs/x.pack.gz',sha=None):
        with self.simulated_checker():
            return s.stage_bytes(self.root,path,'ar',self.sha if sha is None else sha)

    def test_repeated_staging_is_deterministic(self):
        a,_=self.stage();b,_=self.stage()
        self.assertEqual(a,b)

    def test_staged_archive_contains_only_expected_paths(self):
        binary,receipt=self.stage()
        with gzip.GzipFile(fileobj=io.BytesIO(binary)) as gz:
            with tarfile.open(fileobj=io.BytesIO(gz.read())) as archive:
                self.assertEqual(archive.getnames(),['manifest.json','packs/candidate.pack.gz'])
                manifest=json.loads(archive.extractfile('manifest.json').read())
                self.assertFalse(manifest['publication_approved'])
                self.assertEqual(archive.extractfile('packs/candidate.pack.gz').read(),self.data)
        self.assertFalse(receipt['signature_verified'])

    def test_dry_stage_bytes_has_no_filesystem_outputs(self):
        self.stage()
        self.assertFalse((self.root/'tools').exists())

    def test_wrong_archive_sha_blocks(self):
        with self.assertRaisesRegex(s.StageBlocked,'SHA-256 mismatch'):
            self.stage(sha='a'*64)

    def test_invalid_gzip_blocks(self):
        bad=b'not gzip'
        (self.root/'packs/x.pack.gz').write_bytes(bad)
        with self.assertRaisesRegex(s.StageBlocked,'invalid or oversized'):
            self.stage(sha=hashlib.sha256(bad).hexdigest())

    def test_bounded_expansion_blocks(self):
        blob=gzip.compress(b'x'*200,mtime=0)
        (self.root/'packs/x.pack.gz').write_bytes(blob)
        with patch.object(s,'MAX_ENVELOPE',100):
            with self.assertRaisesRegex(s.StageBlocked,'expansion limit'):
                self.stage(sha=hashlib.sha256(blob).hexdigest())

    def test_traversal_blocks(self):
        with self.assertRaisesRegex(s.StageBlocked,'unsafe'):
            self.stage(path='../evil')

    def test_symlink_blocks(self):
        (self.root/'packs/a.pack.gz').symlink_to(self.root/'packs/x.pack.gz')
        with self.assertRaisesRegex(s.StageBlocked,'symlinked'):
            self.stage(path='packs/a.pack.gz')

    def test_fixture_cannot_stage(self):
        with self.simulated_checker(fixture=True):
            with self.assertRaisesRegex(s.StageBlocked,'fixture'):
                s.stage_bytes(self.root,'packs/x.pack.gz','ar',self.sha)

    def test_caller_claimed_approval_rejected(self):
        with self.simulated_checker(approved=True):
            with self.assertRaisesRegex(s.StageBlocked,'self-publishing'):
                s.stage_bytes(self.root,'packs/x.pack.gz','ar',self.sha)

    def test_immutable_replay_and_collision(self):
        payload,_=self.stage()
        first=s.persist_stage(self.root,payload)
        self.assertEqual(first,s.persist_stage(self.root,payload))
        first.write_bytes(b'tampered')
        with self.assertRaisesRegex(s.StageBlocked,'collision'):
            s.persist_stage(self.root,payload)

    def test_interrupted_write_removes_stage(self):
        payload,_=self.stage()
        with patch.object(s.os,'link',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):s.persist_stage(self.root,payload)
        self.assertEqual(list((self.root/'tools/release_publication/candidates').iterdir()),[])

    def test_cli_publish_always_rejected(self):
        exit_code=s.main(['--repo-root',str(self.root),'--artifact-path','packs/x.pack.gz',
                          '--language','ar','--sha256',self.sha,'--publish'])
        self.assertEqual(exit_code,2)
        self.assertFalse((self.root/'tools').exists())

if __name__=='__main__':unittest.main()
