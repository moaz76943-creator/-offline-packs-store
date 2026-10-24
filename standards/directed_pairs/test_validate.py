import unittest
import json
from pathlib import Path
from standards.directed_pairs.validate import validate, verify_compatible, DirectedPairError

FIXTURES_DIR = Path(__file__).parent / 'fixtures'

class TestDirectedPairsValidation(unittest.TestCase):
    def test_valid_pairs(self):
        with open(FIXTURES_DIR / 'valid_pairs.json', encoding='utf-8') as f:
            document = json.load(f)
        self.assertEqual(validate(document), document)

    def test_invalid_orphan_target(self):
        with open(FIXTURES_DIR / 'invalid_orphan.json', encoding='utf-8') as f:
            document = json.load(f)
        with self.assertRaisesRegex(DirectedPairError, 'orphan target sense ID'):
            validate(document)

    def test_invalid_lang_mismatch(self):
        with open(FIXTURES_DIR / 'invalid_lang_mismatch.json', encoding='utf-8') as f:
            document = json.load(f)
        with self.assertRaisesRegex(DirectedPairError, 'source language mismatch'):
            validate(document)

    def test_verify_compatible_success(self):
        with open(FIXTURES_DIR / 'valid_pairs.json', encoding='utf-8') as f:
            doc1 = json.load(f)

        # doc2 adds a new sense and translation, compatible update
        doc2 = json.loads(json.dumps(doc1))
        doc2['senses'].append({
            "sense_id": "sense.fr.banque.finance",
            "language": "fr"
        })
        doc2['directed_translations'].append({
            "translation_id": "tr.en.fr.bank.finance",
            "source_sense_id": "sense.en.bank.finance",
            "target_sense_id": "sense.fr.banque.finance",
            "source_language": "en",
            "target_language": "fr",
            "text": "banque",
            "equivalence": "exact",
            "source": {
                "provenance_id": "fixture.provenance.1",
                "source_version": "1.0"
            }
        })

        self.assertTrue(verify_compatible(doc1, doc2))

    def test_verify_compatible_failure_removed_sense(self):
        with open(FIXTURES_DIR / 'valid_pairs.json', encoding='utf-8') as f:
            doc1 = json.load(f)

        doc2 = json.loads(json.dumps(doc1))
        doc2['senses'].pop() # Remove a sense

        with self.assertRaisesRegex(DirectedPairError, 'breaking removal of sense'):
            verify_compatible(doc1, doc2)

    def test_homograph_variant(self):
        with open(FIXTURES_DIR / 'homograph_variant.json', encoding='utf-8') as f:
            document = json.load(f)
        self.assertEqual(validate(document), document)


if __name__ == '__main__':
    unittest.main()
