"""Metadata-only release receipts are never publisher or corpus-processing evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.final_release_evidence import audit as e

class TruthfulReleaseTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve()
        (self.root/'legal/ledger').mkdir(parents=True)
        self.manifest={'languages':[{'code':f'x{i:02d}'} for i in range(100)],'packs':[],
                       'intellectual_property_status':'UNVERIFIED_RIGHTS'}
        self.ledger={'schema_version':'1.0.0','sources':[]}
        self.version={'release_status':'BLOCKED_DEPENDENCY','latest_verified_version':None}
        self.write()

    def write(self):
        (self.root/'manifest.json').write_text(json.dumps(self.manifest))
        (self.root/'legal/ledger/sources.json').write_text(json.dumps(self.ledger))
        (self.root/'version.json').write_text(json.dumps(self.version))

    def test_zero_jobs_is_not_processing(self):
        r=e.audit(self.root,{'claimed_jobs':0})
        self.assertEqual(r['workflow_validation'],'NOT_RUN')
        self.assertFalse(r['corpus_processing_succeeded'])
        self.assertFalse(r['publication_approved'])

    def test_absent_jobs_not_run(self):
        self.assertEqual(e.audit(self.root)['workflow_validation'],'NOT_RUN')

    def test_unverified_positive_claim_not_pass(self):
        r=e.audit(self.root,{'claimed_jobs':3})
        self.assertEqual(r['workflow_validation'],'UNVERIFIED_EXTERNAL_CLAIM')
        self.assertFalse(r['workflow_jobs_independently_verified'])

    def test_no_source_always_blocked(self):
        self.assertEqual(e.audit(self.root)['status'],'BLOCKED_SOURCE')

    def test_self_claimed_license_not_verified(self):
        self.manifest['intellectual_property_status']='PUBLIC_DOMAIN_ZERO_COPYRIGHT'
        self.ledger['sources']=[{'status':'APPROVED_FOR_REDISTRIBUTION'}]
        self.version['release_status']='VERIFIED_CANDIDATE'
        self.version['latest_verified_version']='4.0.0'
        self.manifest['packs']=[{'id':'fixture'}]
        self.write()
        report=e.audit(self.root,{'claimed_jobs':10})
        self.assertFalse(report['release_ready'])
        self.assertFalse(report['publication_approved'])
        self.assertEqual(report['verified_real_packs'],0)

    def test_missing_language_identity_blocks(self):
        self.manifest['languages'].pop()
        self.write()
        with self.assertRaisesRegex(e.EvidenceBlocked,'100 language'):
            e.audit(self.root)

    def test_duplicate_registration_blocks(self):
        self.manifest['languages'][1]['code']=self.manifest['languages'][0]['code']
        self.write()
        with self.assertRaises(e.EvidenceBlocked):e.audit(self.root)

    def test_invalid_workflow_job_count_blocks(self):
        with self.assertRaisesRegex(e.EvidenceBlocked,'invalid workflow'):
            e.audit(self.root,{'claimed_jobs':'3'})

    def test_duplicate_manifest_json_key_blocks(self):
        (self.root/'manifest.json').write_text('{"languages":[],"languages":[]}')
        with self.assertRaises(e.EvidenceBlocked):e.audit(self.root)

    def test_immutable_repeat_and_collision(self):
        r=e.audit(self.root)
        first=e.persist(self.root,r)
        self.assertEqual(first,e.persist(self.root,r))
        first.write_text('tampered')
        with self.assertRaisesRegex(e.EvidenceBlocked,'collision'):e.persist(self.root,r)

    def test_interrupted_write_cleans_staging(self):
        with patch.object(e.os,'link',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):e.persist(self.root,e.audit(self.root))
        self.assertEqual(list((self.root/'tools/final_release_evidence/handoffs').iterdir()),[])

    def test_handoff_cannot_claim_ready(self):
        r=e.audit(self.root);r['release_ready']=True
        with self.assertRaisesRegex(e.EvidenceBlocked,'cannot issue'):e.persist(self.root,r)

if __name__=='__main__':unittest.main()
