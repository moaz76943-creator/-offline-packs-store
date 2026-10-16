"""Isolated bounded and immutable provenance compiler tests; mock rights grants are never published."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch
from tools.provenance_release import evidence

class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name).resolve()
        (self.root/'legal/ledger/daily').mkdir(parents=True)
        (self.root/'packs').mkdir()
        (self.root/'packs/fixture.pack.gz').write_bytes(b'fixture')
        self.sha=hashlib.sha256(b'fixture').hexdigest()
        self.ledger={'schema_version':'1.0.0','sources':[]}
        self.candidates=[]
        self.write()

    def write(self):
        (self.root/'legal/ledger/sources.json').write_text(json.dumps(self.ledger))
        (self.root/'manifest.json').write_text(json.dumps({'languages':[], 'packs':[], 'intellectual_property_status':'UNVERIFIED_RIGHTS'}))
        (self.root/'legal/ledger/daily/2026-10-13.json').write_text(json.dumps({'schema_version':'1.0.0','date':'2026-10-13','release_candidates':self.candidates}))

    def fixture(self):
        self.ledger['sources']=[{'source_id':'s1','dataset_version':'v1','status':'APPROVED_FOR_REDISTRIBUTION',
            'publisher':'Test-only','origin_url':'https://example.org/test',
            'retrieval':{'sha256':'b'*64},'license':{'id':'CC0-1.0'}}]
        self.candidates=[{'asset_id':'pack.ar','artifact_path':'packs/fixture.pack.gz','sha256':self.sha,
            'output_license_id':'CC0-1.0','source_refs':[{'source_id':'s1','dataset_version':'v1','artifact_sha256':'b'*64}]}]
        self.write()

    def simulated_rights(self):
        legal=ModuleType('legal');legal.__path__=[]
        ledger=ModuleType('legal.ledger');ledger.__path__=[]
        admission=ModuleType('legal.ledger.admission');admission.evaluate=lambda *args: []
        return patch.dict(sys.modules,{'legal':legal,'legal.ledger':ledger,'legal.ledger.admission':admission})

    def test_empty_claimed_corpus_never_compiles(self):
        with self.simulated_rights():
            with self.assertRaisesRegex(evidence.ProvenanceBlocked,'zero admitted'):
                evidence.compile_provenance(self.root)

    def test_synthetic_stub_only_quarantines_even_if_license_check_mocked(self):
        self.fixture()
        with self.simulated_rights():
            receipt=evidence.compile_provenance(self.root)
        self.assertEqual(receipt['status'],'QUARANTINED_PENDING_PACK_AND_SIGNATURE_QA')
        self.assertFalse(receipt['publication_approved'])
        self.assertFalse(receipt['sqlite_v2_verified'])
        self.assertFalse(receipt['corpus_processing_succeeded'])

    def test_archive_hash_mismatch_blocks(self):
        self.fixture();self.candidates[0]['sha256']='c'*64;self.write()
        with self.simulated_rights():
            with self.assertRaisesRegex(evidence.ProvenanceBlocked,'hash mismatch'):
                evidence.compile_provenance(self.root)

    def test_changed_source_snapshot_blocks(self):
        self.fixture();self.candidates[0]['source_refs'][0]['artifact_sha256']='d'*64;self.write()
        with self.simulated_rights():
            with self.assertRaisesRegex(evidence.ProvenanceBlocked,'changed source'):
                evidence.compile_provenance(self.root)

    def test_missing_source_provenance_blocks(self):
        self.fixture();self.candidates[0]['source_refs']=[];self.write()
        with self.simulated_rights():
            with self.assertRaisesRegex(evidence.ProvenanceBlocked,'missing candidate source'):
                evidence.compile_provenance(self.root)

    def test_unverified_source_blocks(self):
        self.fixture();self.ledger['sources'][0]['status']='REVIEW_REQUIRED';self.write()
        with self.simulated_rights():
            with self.assertRaisesRegex(evidence.ProvenanceBlocked,'unverified'):
                evidence.compile_provenance(self.root)

    def test_traversal_blocks(self):
        self.fixture();self.candidates[0]['artifact_path']='../fixture.pack.gz';self.write()
        with self.simulated_rights():
            with self.assertRaisesRegex(evidence.ProvenanceBlocked,'unsafe'):
                evidence.compile_provenance(self.root)

    def test_symlink_blocks(self):
        self.fixture();(self.root/'packs/alias.pack.gz').symlink_to(self.root/'packs/fixture.pack.gz')
        self.candidates[0]['artifact_path']='packs/alias.pack.gz';self.write()
        with self.simulated_rights():
            with self.assertRaisesRegex(evidence.ProvenanceBlocked,'symlinked'):
                evidence.compile_provenance(self.root)

    def test_duplicate_json_keys_block(self):
        (self.root/'manifest.json').write_text('{"languages":[],"languages":[],"packs":[]}')
        with self.assertRaises(evidence.ProvenanceBlocked):
            evidence.read_json(self.root/'manifest.json')

    def test_immutable_repeat_and_collision(self):
        report={'assets':[1],'publication_approved':False}
        first=evidence.persist(self.root,report)
        self.assertEqual(first,evidence.persist(self.root,report))
        first.write_bytes(b'tamper')
        with self.assertRaisesRegex(evidence.ProvenanceBlocked,'collision'):
            evidence.persist(self.root,report)

    def test_interruption_cleans_staging(self):
        with patch.object(evidence.os,'link',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                evidence.persist(self.root,{'assets':[1],'publication_approved':False})
        self.assertEqual(list((self.root/'tools/provenance_release/handoffs').iterdir()),[])

    def test_no_approval_to_write(self):
        with self.assertRaisesRegex(evidence.ProvenanceBlocked,'not eligible'):
            evidence.persist(self.root,{'assets':[1],'publication_approved':True})

if __name__=='__main__':
    unittest.main()
