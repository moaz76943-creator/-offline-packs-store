"""Source-bound relation classifications: no guessed orthographic aliases."""
import hashlib
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.linguistic_extensions.indic_seasian.relations import classify_relation
from tools.linguistic_extensions.indic_seasian.processor import ScriptContractError, evidence_digest


class RelationsTests(unittest.TestCase):
    def test_unicode_canonical_is_not_lexical_attestation(self):
        r = classify_relation('or', 'ଓଡ଼ିଆ', 'ଓଡ଼ିଆ')
        self.assertEqual('canonical_unicode_equivalent', r['status'])
        self.assertFalse(r['lexical_claim'])

    def test_punjabi_cross_script_not_automatic_equivalence(self):
        left, right = 'ਪੰਜਾਬੀ', 'پنجابی'
        self.assertEqual('unresolved', classify_relation('pa', left, right)['status'])
        ledger, proof = self.proof('pa', left, right)
        result = classify_relation('pa', left, right, evidence=proof, ledger=ledger)
        self.assertEqual('attested_relation_only', result['status'])
        self.assertEqual('transliteration', result['relation_kind'])
        self.assertFalse(result['lexical_claim'])
        for forged in ({**proof, 'language_code': 'ur'},
                       {**proof, 'source_sha256': 'b' * 64},
                       {**proof, 'relation_kind': 'equivalent_by_look'},
                       {**proof, 'right_utf8_sha256': 'b' * 64}):
            with self.assertRaises(ScriptContractError):
                classify_relation('pa', left, right, evidence=forged, ledger=ledger)
        with self.assertRaises(ScriptContractError):
            classify_relation('pa', left, right, evidence=proof, ledger={'sources': []})

    def test_non_string_source_id_cannot_crash_lookup(self):
        ledger, proof = self.proof('pa', 'ਪੰਜਾਬੀ', 'پنجابی')
        with self.assertRaises(ScriptContractError):
            classify_relation('pa', 'ਪੰਜਾਬੀ', 'پنجابی',
                              evidence={**proof, 'source_id': []}, ledger=ledger)

    def test_unrelated_forms_not_silently_normalized(self):
        left, right = 'हिन्दी', 'हिंदी'
        self.assertEqual('unresolved', classify_relation('hi', left, right)['status'])
        ledger, proof = self.proof('hi', left, right)
        for kind in ('related_form', 'ambiguous_orthography', 'lexical_equivalent'):
            result = classify_relation('hi', left, right,
                evidence={**proof, 'relation_kind': kind}, ledger=ledger)
            self.assertEqual(kind, result['relation_kind'])
            self.assertEqual(kind == 'lexical_equivalent', result['lexical_claim'])

    def test_same_source_and_text_hashes_cannot_authorize_new_unreviewed_relation(self):
        ledger, record = self.proof('pa', 'ਪੰਜਾਬੀ', 'پنجابی')
        changed = {**record, 'evidence_version': 'unreviewed-v2'}
        with self.assertRaises(ScriptContractError):
            classify_relation('pa', 'ਪੰਜਾਬੀ', 'پنجابی', evidence=changed, ledger=ledger)

    @staticmethod
    def proof(code, a, b):
        evidence = {'language_code': code, 'source_id': 'synthetic-review',
                    'source_sha256': 'a' * 64,
                    'left_utf8_sha256': hashlib.sha256(a.encode()).hexdigest(),
                    'right_utf8_sha256': hashlib.sha256(b.encode()).hexdigest(),
                    'relation_kind': 'transliteration', 'evidence_version': 'synthetic-test-v1'}
        variants = [{**evidence, 'relation_kind': kind}
                    for kind in ('transliteration', 'related_form',
                                 'ambiguous_orthography', 'lexical_equivalent')]
        ledger = {'sources': [{
            'id': 'synthetic-review', 'languages': [code],
            'sha256': 'a' * 64, 'release_approved': True,
            'rights_status': 'APPROVED', 'reviewed_by': 'synthetic-test-reviewer',
            'rights_evidence_sha256': 'b' * 64,
            'reviewed_records': {'morphology': [], 'segmentation': [],
                                 'orthographic_relation': [evidence_digest(x) for x in variants]},
        }]}
        return ledger, evidence


if __name__ == '__main__':
    unittest.main()
