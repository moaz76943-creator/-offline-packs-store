"""Local-only conformance adapter tests. Mocked canonical inspector cannot admit real sources."""
import gzip
import hashlib
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch
from tools.pack_conformance import strict_adapter as c

class AdapterTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve()
        (self.root/'packs').mkdir()
        self.blob=gzip.compress(b'{"fixture":true}',mtime=0)
        self.archive=self.root/'packs/ar.pack.gz'
        self.archive.write_bytes(self.blob)
        self.sha=hashlib.sha256(self.blob).hexdigest()

    def mocked_canonical(self,**options):
        root=ModuleType('tools.gha_factory');root.__path__=[]
        inner=ModuleType('tools.gha_factory.pack_conformance');inner.__path__=[]
        check=ModuleType('tools.gha_factory.pack_conformance.check')
        report={'fixture_only':False,'archive_sha256':self.sha,
                'sqlite_sha256':'a'*64,'source_ids':['pilot-fixture-test'],
                'actual_lexical_count':1,'schema_version':'2.0.0'}
        report.update(options)
        check.inspect=lambda *a,**kw:report
        return patch.dict(sys.modules,{'tools.gha_factory':root,
            'tools.gha_factory.pack_conformance':inner,
            'tools.gha_factory.pack_conformance.check':check})

    def verify(self,rel='packs/ar.pack.gz',sha=None,language='ar',**report):
        with self.mocked_canonical(**report):
            return c.inspect_candidate(self.root,rel,language,self.sha if sha is None else sha)

    def test_no_publication_on_mocked_pass(self):
        report=self.verify()
        self.assertFalse(report['publication_approved'])
        self.assertFalse(report['hosted_jobs_verified'])
        self.assertFalse(report['signature_verified'])

    def test_wrong_archive_hash(self):
        with self.assertRaisesRegex(c.QARejected,'SHA-256 mismatch'):
            self.verify(sha='b'*64)

    def test_unbounded_gzip_rejected(self):
        big=gzip.compress(b'X'*400,mtime=0)
        self.archive.write_bytes(big)
        with patch.object(c,'MAX_ENVELOPE',100):
            with self.assertRaisesRegex(c.QARejected,'decompression limit'):
                self.verify(sha=hashlib.sha256(big).hexdigest())

    def test_malformed_archive_rejected(self):
        bad=b'not a gzip'
        self.archive.write_bytes(bad)
        with self.assertRaisesRegex(c.QARejected,'invalid compressed'):
            self.verify(sha=hashlib.sha256(bad).hexdigest())

    def test_symlink_rejected(self):
        (self.root/'packs/link.pack.gz').symlink_to(self.archive)
        with self.assertRaisesRegex(c.QARejected,'symlink'):
            self.verify(rel='packs/link.pack.gz')

    def test_traversal_rejected(self):
        with self.assertRaisesRegex(c.QARejected,'unsafe'):
            self.verify(rel='../other.pack.gz')

    def test_wrong_language_identity_rejected(self):
        with self.assertRaisesRegex(c.QARejected,'invalid language'):
            self.verify(language='../ar')

    def test_fixture_cannot_pass(self):
        with self.assertRaisesRegex(c.QARejected,'synthetic'):
            self.verify(fixture_only=True)

    def test_missing_source_provenance_cannot_pass(self):
        with self.assertRaisesRegex(c.QARejected,'incomplete'):
            self.verify(source_ids=[])

    def test_wrong_canonical_archive_sha_cannot_pass(self):
        with self.assertRaisesRegex(c.QARejected,'inconsistent'):
            self.verify(archive_sha256='b'*64)

    def test_canonical_wrong_language_failure_propagates(self):
        with self.mocked_canonical():
            def forbidden(*args,**kwargs):
                if args[1]!='de':raise c.QARejected('wrong-language record')
            from tools.gha_factory.pack_conformance import check
            check.inspect=forbidden
            with self.assertRaisesRegex(c.QARejected,'wrong-language'):
                c.inspect_candidate(self.root,'packs/ar.pack.gz','ar',self.sha)

    def test_replay_is_deterministic_and_nondestructive(self):
        before=self.archive.read_bytes()
        self.assertEqual(self.verify(),self.verify())
        self.assertEqual(before,self.archive.read_bytes())

if __name__=='__main__':unittest.main()
