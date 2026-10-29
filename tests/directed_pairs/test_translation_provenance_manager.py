import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.directed_pairs.translation_provenance_manager import (
    validate_translation_edge,
    batch_audit_edges,
)

class TestTranslationProvenanceManager(unittest.TestCase):
    def test_valid_directed_edge(self):
        res = validate_translation_edge(
            source_lemma="Buch",
            target_gloss="كتاب",
            source_lang="de",
            target_lang="ar",
            provenance_source="kaikki_core",
            license_tag="CC-BY-SA-4.0",
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["directed_edge"], "de_ar")
        self.assertEqual(res["source_lemma"], "Buch")
        self.assertTrue(res["is_asymmetric"])

    def test_unapproved_license_rejected(self):
        res = validate_translation_edge(
            source_lemma="Wort",
            target_gloss="كلمة",
            source_lang="de",
            target_lang="ar",
            provenance_source="unknown",
            license_tag="PROPRIETARY_UNAPPROVED",
        )
        self.assertIsNone(res)

    def test_batch_auditing(self):
        raw = [
            {"src_lemma": "Wasser", "tgt_gloss": "ماء", "license": "CC0-1.0"},
            {"src_lemma": "", "tgt_gloss": "فارغ", "license": "CC0-1.0"}, # فارغ يجب حذفه
        ]
        audited = batch_audit_edges(raw)
        self.assertEqual(len(audited), 1)

if __name__ == '__main__':
    unittest.main()
