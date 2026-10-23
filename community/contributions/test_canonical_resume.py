"""Exercise intake with its real lexical validator; all input is test-only."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from community.contributions.ingest import ingest

ROOT = Path(__file__).resolve().parents[2]


class CanonicalIntake(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.staging = self.root / 'staging'
        self.document = json.loads((ROOT/'standards/lexical/fixtures/positive.json').read_text())
        source = {
            'source_id':'self-authored-intake-test', 'dataset_version':'test-v1',
            'record_locator':'test-record', 'license_id':'CC0-1.0',
            'publisher':'Test author', 'origin_url':'https://example.org/test',
            'artifact_sha256':hashlib.sha256(b'self-authored test bytes').hexdigest(),
            'fixture_only':False, 'publication_approved':False, 'retrieval_id':'isolated-test',
        }
        def provenance(value):
            if isinstance(value, dict):
                for key in list(value):
                    if key == 'source':
                        value[key] = copy.deepcopy(source)
                    else:
                        provenance(value[key])
            elif isinstance(value, list):
                for item in value:
                    provenance(item)
        provenance(self.document)
        self.input = self.root/'input.json'
        self.input.write_text(json.dumps(self.document))

    def receipt(self):
        return ingest(self.input, self.staging)

    def test_real_validator_stages_without_approving_rights(self):
        receipt = self.receipt()
        self.assertEqual(receipt['state'], 'STAGED_REVIEW_REQUIRED')
        self.assertFalse(receipt['rights_approved'])
        self.assertEqual(self.receipt(), receipt)

    def test_interrupted_blob_only_transaction_resumes_twice(self):
        data = self.input.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        staged = self.staging/'staged'
        staged.mkdir(parents=True)
        path = staged/(digest+'.bin')
        path.write_bytes(data)
        first = self.receipt()
        index = self.staging/'records'/(digest+'.json')
        before = (path.read_bytes(), index.read_bytes())
        self.assertEqual(self.receipt(), first)
        self.assertEqual((path.read_bytes(), index.read_bytes()), before)

    def test_contradictory_orphan_receipt_is_not_overwritten(self):
        first = self.receipt()
        blob = self.staging/'staged'/first['file']
        blob.unlink()
        index = self.staging/'records'/(first['sha256']+'.json')
        index.write_text('{"state":"forged"}')
        before = index.read_bytes()
        with self.assertRaisesRegex(ValueError, 'index mismatch'):
            self.receipt()
        self.assertEqual(index.read_bytes(), before)
        self.assertFalse(blob.exists())

    def test_valid_orphan_receipt_recovers_blob_without_changing_evidence(self):
        first = self.receipt()
        blob = self.staging/'staged'/first['file']
        blob.unlink()
        index = self.staging/'records'/(first['sha256']+'.json')
        index.write_text(json.dumps(first, indent=2))
        before = index.read_bytes()
        self.assertEqual(self.receipt(), first)
        self.assertEqual(blob.read_bytes(), self.input.read_bytes())
        self.assertEqual(index.read_bytes(), before)

    def test_corrupt_surviving_blob_is_not_repaired_as_success(self):
        first = self.receipt()
        blob = self.staging/'staged'/first['file']
        blob.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'collision'):
            self.receipt()
        self.assertEqual(blob.read_bytes(), b'corrupt')

    def test_real_schema_rejects_malformed_ids_before_duplicate_indexing(self):
        self.document['lexemes'][0]['lexeme_id'] = ['invalid']
        self.input.write_text(json.dumps(self.document))
        with self.assertRaises(ValueError):
            self.receipt()
        self.assertFalse(self.staging.exists())

    def test_duplicate_ids_across_valid_documents_in_archive_are_rejected(self):
        second = copy.deepcopy(self.document)
        second['document_id'] += '.second'
        archive = self.root/'duplicate.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('one.json', json.dumps(self.document))
            z.writestr('two.json', json.dumps(second))
        with self.assertRaisesRegex(ValueError, 'duplicate entry ID'):
            ingest(archive, self.staging)
        self.assertFalse(self.staging.exists())
