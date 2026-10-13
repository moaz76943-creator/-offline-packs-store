"""Focused offline adversarial admission tests; no real source clearance claimed."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch
from tools.ingestion_circuit_breaker import gate

class CircuitBreakerTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.root=Path(t.name).resolve()
        (self.root/'legal/ledger/daily').mkdir(parents=True)
        (self.root/'sources').mkdir()
        self.source=self.root/'sources/original.json'
        self.source.write_text('source bytes',encoding='utf-8')
        self.sha=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.ledger={'schema_version':'1.0.0','sources':[]}
        self.persist()

    def persist(self):
        (self.root/'legal/ledger/sources.json').write_text(json.dumps(self.ledger))
        (self.root/'manifest.json').write_text(json.dumps({'languages':[], 'packs':[], 'intellectual_property_status':'UNVERIFIED_RIGHTS'}))
        (self.root/'legal/ledger/daily/one.json').write_text('{"schema_version":"1.0.0","release_candidates":[]}')

    def fill_source(self,status='APPROVED_FOR_REDISTRIBUTION'):
        self.ledger['sources']=[{'source_id':'source-1','dataset_version':'1.0',
            'status':status,'retrieval':{'artifact_path':'sources/original.json','sha256':self.sha},
            'license':{'id':'CC0-1.0'},'review':{'reviewer':'test'}}]
        self.persist()

    def invoke(self,**kwargs):
        return gate.admit(self.root,kwargs.get('source_path','sources/original.json'),
                          'source-1',kwargs.get('sha',self.sha),integrate=kwargs.get('integrate',False))

    def test_unverified_ledger_blocks(self):
        with self.assertRaisesRegex(gate.GateBlocked,'not uniquely recorded'):
            self.invoke()

    def test_review_required_blocks(self):
        self.fill_source('REVIEW_REQUIRED')
        with self.assertRaisesRegex(gate.GateBlocked,'not independently approved'):
            self.invoke()

    def test_missing_sha_blocks(self):
        with self.assertRaisesRegex(gate.GateBlocked,'expected SHA-256'):
            self.invoke(sha=None)

    def test_wrong_sha_blocks(self):
        with self.assertRaisesRegex(gate.GateBlocked,'source bytes differ'):
            self.invoke(sha='a'*64)

    def test_symlink_escape_blocks(self):
        (self.root/'sources/alias.json').symlink_to(self.source)
        with self.assertRaisesRegex(gate.GateBlocked,'symlinked'):
            self.invoke(source_path='sources/alias.json')

    def test_traversal_blocks(self):
        with self.assertRaisesRegex(gate.GateBlocked,'unsafe'):
            self.invoke(source_path='../other')

    def test_missing_snapshot_blocks(self):
        with self.assertRaisesRegex(gate.GateBlocked,'missing source'):
            self.invoke(source_path='sources/missing')

    def test_duplicate_json_properties_block(self):
        (self.root/'legal/ledger/sources.json').write_text('{"sources":[],"sources":[]}')
        with self.assertRaises(gate.GateBlocked):
            self.invoke()

    def test_fake_hash_in_ledger_blocks(self):
        self.fill_source()
        self.ledger['sources'][0]['retrieval']['sha256']='a'*64
        self.persist()
        with self.assertRaisesRegex(gate.GateBlocked,'not independently approved'):
            self.invoke()

    def test_same_bytes_wrong_source_path_blocks(self):
        self.fill_source()
        (self.root/'sources/copy.json').write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(gate.GateBlocked,'not independently approved'):
            self.invoke(source_path='sources/copy.json')

    def simulated_admission(self):
        legal = ModuleType('legal'); legal.__path__=[]
        ledger = ModuleType('legal.ledger'); ledger.__path__=[]
        admission = ModuleType('legal.ledger.admission')
        admission.evaluate = lambda *_: []
        return patch.dict(sys.modules, {'legal':legal,'legal.ledger':ledger,
                                        'legal.ledger.admission':admission})

    def test_fake_approval_still_only_quarantines(self):
        self.fill_source()
        with self.simulated_admission():
            receipt=self.invoke()
        self.assertEqual(receipt['status'],'QUARANTINED_PENDING_COORDINATOR')
        self.assertFalse(receipt['publication_approved'])
        self.assertFalse(receipt['corpus_processing_succeeded'])

    def test_integrate_must_return_blocker_even_if_source_evidence_passes(self):
        self.fill_source()
        with self.simulated_admission():
            with self.assertRaisesRegex(gate.GateBlocked,'BLOCKED_INTEGRATION'):
                self.invoke(integrate=True)

    def test_repeated_verification_is_deterministic(self):
        self.fill_source()
        with self.simulated_admission():
            self.assertEqual(self.invoke(),self.invoke())

if __name__=='__main__':
    unittest.main()
