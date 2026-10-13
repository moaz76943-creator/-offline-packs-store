"""Adversarial focused offline validation: no synthetic artifact can be published."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
from types import ModuleType

from tools.release_validation import candidate_handoff as gate


class CandidateHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'legal/ledger/daily').mkdir(parents=True)
        (self.root / 'legal/ledger/sources.json').write_text('{"schema_version":"1.0.0","sources":[]}')
        (self.root / 'manifest.json').write_text('{"intellectual_property_status":"UNVERIFIED_RIGHTS","languages":[],"packs":[]}')
        (self.root / 'packs').mkdir()
        (self.root / 'packs/a.pack.gz').write_bytes(b'fixture')
        self.sha = hashlib.sha256(b'fixture').hexdigest()

    def test_missing_provenance_blocks_even_if_bytes_match(self):
        admission = ModuleType('legal.ledger.admission')
        admission.evaluate = lambda *args: []
        with patch.dict(sys.modules, {'legal': ModuleType('legal'),
                                      'legal.ledger': ModuleType('legal.ledger'),
                                      'legal.ledger.admission': admission}):
            with self.assertRaisesRegex(gate.Blocked, 'UNVERIFIED_RIGHTS'):
                gate.release_evidence(self.root, 'packs/a.pack.gz', self.sha, 'ar')

    def test_wrong_sha_rejected(self):
        with self.assertRaisesRegex(gate.Blocked, 'SHA-256 mismatch'):
            gate.release_evidence(self.root, 'packs/a.pack.gz', 'a'*64, 'ar')

    def test_symlink_escape_rejected(self):
        outside = self.root.parent / (self.root.name + '-other')
        outside.write_bytes(b'fixture')
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        (self.root / 'packs/out.pack.gz').symlink_to(outside)
        with self.assertRaisesRegex(gate.Blocked, 'symlinked'):
            gate.release_evidence(self.root, 'packs/out.pack.gz', self.sha, 'ar')

    def test_traversal_rejected(self):
        with self.assertRaisesRegex(gate.Blocked, 'unsafe'):
            gate.release_evidence(self.root, '../outside.pack.gz', self.sha, 'ar')

    def test_malformed_archive_not_admitted(self):
        (self.root / 'legal/ledger/daily/one.json').write_text('{not json')
        with self.assertRaises(gate.Blocked):
            gate.release_evidence(self.root, 'packs/a.pack.gz', self.sha, 'ar')

    def test_duplicate_json_keys_rejected(self):
        p = self.root / 'duplicate.json'
        p.write_text('{"status":"APPROVED","status":"BLOCKED"}')
        with self.assertRaises(gate.Blocked):
            gate.strict_json(p)

    def test_oversized_input_rejected(self):
        with patch.object(gate, 'MAX_PACK', 2):
            with self.assertRaisesRegex(gate.Blocked, 'byte limit'):
                gate.release_evidence(self.root, 'packs/a.pack.gz', self.sha, 'ar')

    def test_repeated_write_is_byte_identical(self):
        evidence = {'archive_sha256':self.sha, 'publication_approved':False, 'status':'QUARANTINED'}
        p1 = gate.write_handoff(self.root, evidence)
        p2 = gate.write_handoff(self.root, evidence)
        self.assertEqual(p1,p2)
        self.assertEqual(p1.read_bytes(),gate.canonical_json(evidence))

    def test_immutable_collision_rejected(self):
        evidence = {'archive_sha256': self.sha, 'publication_approved':False}
        gate.write_handoff(self.root, evidence)
        with self.assertRaisesRegex(gate.Blocked, 'collision'):
            gate.write_handoff(self.root, {'archive_sha256':self.sha,'publication_approved':False,'different':1})

    def test_interrupted_handoff_leaves_no_published_partial(self):
        evidence = {'archive_sha256':self.sha,'publication_approved':False}
        with patch.object(gate.os,'link',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                gate.write_handoff(self.root,evidence)
        out = self.root / 'tools/release_validation/handoffs'
        self.assertEqual(list(out.iterdir()),[])

    def test_handoff_cannot_claim_approval(self):
        with self.assertRaisesRegex(gate.Blocked,'cannot authorize'):
            gate.write_handoff(self.root, {'archive_sha256':self.sha, 'publication_approved':True})

    def test_handoff_rejects_path_as_digest(self):
        with self.assertRaisesRegex(gate.Blocked, 'invalid handoff'):
            gate.write_handoff(self.root, {'archive_sha256':'../evil', 'publication_approved':False})

    def test_no_successful_jobs_claim(self):
        example = {'archive_sha256':self.sha,'publication_approved':False,
                   'corpus_processing_succeeded':False,'claimed_jobs_verified':False}
        result = gate.write_handoff(self.root,example)
        report = json.loads(result.read_text())
        self.assertFalse(report['corpus_processing_succeeded'])


if __name__ == '__main__':
    unittest.main()
