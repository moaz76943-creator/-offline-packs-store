"""Offline adversarial tests: mocks cannot demonstrate authentic corpus eligibility."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch
from tools.pack_manifest import safe_manifest as m

class ManifestTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name).resolve()
        (self.root/'packs').mkdir()
        self.archive=gzip.compress(b'{"fixture":true}',mtime=0)
        (self.root/'packs/fixture.pack.gz').write_bytes(self.archive)
        self.sha=hashlib.sha256(self.archive).hexdigest()
        self.claims=[{'language':'ar','artifact_path':'packs/fixture.pack.gz','archive_sha256':self.sha}]

    def inspect_stub(self):
        tools=ModuleType('tools.gha_factory');tools.__path__=[]
        pack=ModuleType('tools.gha_factory.pack_conformance');pack.__path__=[]
        check=ModuleType('tools.gha_factory.pack_conformance.check')
        check.inspect=lambda *args,**kwargs:{'fixture_only':False,'publication_approved':False,
            'sqlite_sha256':'b'*64,'actual_lexical_count':1,'source_ids':['test-source'],
            'schema_version':'2.0.0'}
        return patch.dict(sys.modules,{'tools.gha_factory':tools,
            'tools.gha_factory.pack_conformance':pack,
            'tools.gha_factory.pack_conformance.check':check})

    def generate(self,claims=None):
        with self.inspect_stub():
            return m.manifest(self.root,self.claims if claims is None else claims)

    def test_empty_candidate_list_fails(self):
        with self.assertRaisesRegex(m.ManifestBlocked,'zero candidates'):
            self.generate([])

    def test_mocked_valid_candidate_still_not_publishable(self):
        result=self.generate()
        self.assertFalse(result['publication_approved'])
        self.assertFalse(result['stable_id_migration_verified'])
        self.assertFalse(result['signature_verified'])

    def test_wrong_hash_rejected(self):
        bad=[dict(self.claims[0],archive_sha256='c'*64)]
        with self.assertRaisesRegex(m.ManifestBlocked,'hash mismatch'):
            self.generate(bad)

    def test_duplicate_language_rejected(self):
        with self.assertRaisesRegex(m.ManifestBlocked,'duplicate'):
            self.generate(self.claims*2)

    def test_wrong_language_syntax(self):
        bad=[dict(self.claims[0],language='../ar')]
        with self.assertRaisesRegex(m.ManifestBlocked,'invalid candidate'):
            self.generate(bad)

    def test_traversal_rejected(self):
        bad=[dict(self.claims[0],artifact_path='../outside')]
        with self.assertRaisesRegex(m.ManifestBlocked,'unsafe'):
            self.generate(bad)

    def test_symlink_escape_rejected(self):
        (self.root/'packs/link.pack.gz').symlink_to(self.root/'packs/fixture.pack.gz')
        bad=[dict(self.claims[0],artifact_path='packs/link.pack.gz')]
        with self.assertRaisesRegex(m.ManifestBlocked,'symlinked'):
            self.generate(bad)

    def test_malformed_archive_rejected(self):
        body=b'not gzip'
        (self.root/'packs/fixture.pack.gz').write_bytes(body)
        self.claims[0]['archive_sha256']=hashlib.sha256(body).hexdigest()
        with self.assertRaisesRegex(m.ManifestBlocked,'invalid gzip'):
            self.generate()

    def test_decompression_bomb_rejected_bounded(self):
        body=gzip.compress(b'X'*250,mtime=0)
        (self.root/'packs/fixture.pack.gz').write_bytes(body)
        self.claims[0]['archive_sha256']=hashlib.sha256(body).hexdigest()
        with patch.object(m,'MAX_ENVELOPE',100):
            with self.assertRaisesRegex(m.ManifestBlocked,'decompression limit'):
                self.generate()

    def test_safe_diff_requires_manual_id_review(self):
        old=self.generate();new=json.loads(json.dumps(old));new['packs'][0]['archive_sha256']='d'*64
        new['packs'][0]['sqlite_sha256']='e'*64
        diff=m.diff(old,new)
        self.assertEqual(diff['changed_pending_stable_id_review'],['ar'])
        self.assertFalse(diff['safe_to_apply'])

    def test_repeat_immutable_and_collision(self):
        val=self.generate();p=m.persist(self.root,val)
        self.assertEqual(p,m.persist(self.root,val))
        p.write_bytes(b'tampered')
        with self.assertRaisesRegex(m.ManifestBlocked,'collision'):
            m.persist(self.root,val)

    def test_interrupted_write_cleans_stage(self):
        with patch.object(m.os,'link',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):m.persist(self.root,self.generate())
        self.assertEqual(list((self.root/'tools/pack_manifest/handoffs').iterdir()),[])

    def test_no_auto_removal(self):
        old=self.generate();new={'packs':[],'publication_approved':False}
        plan=m.diff(old,new)
        self.assertEqual(plan['removed_pending_review'],['ar'])
        self.assertFalse(plan['safe_to_apply'])

    def test_cli_imports_checker_without_pythonpath(self):
        spec=self.root/'candidates.json'
        spec.write_text(json.dumps(self.claims),encoding='utf-8')
        script=Path(__file__).resolve().parent/'safe_manifest.py'
        env=os.environ.copy()
        env.pop('PYTHONPATH',None)
        completed=subprocess.run([sys.executable,str(script),'--repo-root',str(self.root),
                                  '--candidate-spec',str(spec)],
                                 cwd=self.root,env=env,capture_output=True,text=True,check=False)
        combined=completed.stdout+completed.stderr
        self.assertNotIn("No module named 'tools'",combined)
        self.assertNotIn('ModuleNotFoundError',combined)
        self.assertIn('publication_approved',completed.stdout)

    def test_archive_open_does_not_follow_final_symlink(self):
        secret=self.root/'secret.pack.gz'
        secret.write_bytes(b'private-archive-bytes')
        link=self.root/'packs'/'alias.pack.gz'
        link.symlink_to(secret)
        with self.assertRaises(m.ManifestBlocked):
            m.archive_bytes(link)
        self.assertEqual(secret.read_bytes(),b'private-archive-bytes')

    def test_stat_size_cannot_authorize_an_oversized_read(self):
        path=self.root/'packs'/'grown.pack.gz'
        path.write_bytes(b'X'*300)
        fake=os.stat_result((stat.S_IFREG,0,0,1,0,0,10,0,0,0))
        with patch.object(m,'MAX_ARCHIVE',100),patch.object(Path,'stat',lambda _self,*_a,**_k: fake):
            with self.assertRaisesRegex(m.ManifestBlocked,'exceeds max bytes'):
                m.archive_bytes(path)

    def test_unchanged_sqlite_skips_repackaging(self):
        old = self.generate()
        new = json.loads(json.dumps(old))

        # Change archive_sha256 but keep sqlite_sha256 the same
        new['packs'][0]['archive_sha256'] = 'd'*64

        diff = m.diff(old, new)
        self.assertEqual(diff['unchanged'], ['ar'])
        self.assertEqual(diff['changed_pending_stable_id_review'], [])

    def test_changed_sqlite_triggers_review(self):
        old = self.generate()
        new = json.loads(json.dumps(old))

        # Change sqlite_sha256
        new['packs'][0]['sqlite_sha256'] = 'e'*64

        diff = m.diff(old, new)
        self.assertEqual(diff['changed_pending_stable_id_review'], ['ar'])
        self.assertEqual(diff['unchanged'], [])

if __name__=='__main__':unittest.main()
