import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.workers.examples_worker import align_directed_example, batch_align_examples

class TestExamplesWorker(unittest.TestCase):
    def test_directed_alignment(self):
        record = align_directed_example(
            source_text="Das Buch ist gut.",
            target_text="الكتاب جيد.",
            source_lang="de",
            target_lang="ar",
            lemma="Buch",
            cefr_level="A1"
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["directed_pair"], "de_ar")
        self.assertEqual(record["source_sentence"], "Das Buch ist gut.")
        self.assertEqual(record["target_sentence"], "الكتاب جيد.")

    def test_invalid_empty_filtered(self):
        record = align_directed_example("", "", "de", "ar", "Buch")
        self.assertIsNone(record)

    def test_batch_alignment(self):
        raw_list = [
            {"src": "Wasser", "tgt": "ماء", "src_lang": "de", "tgt_lang": "ar", "lemma": "Wasser"},
            {"src": "X", "tgt": "Y", "src_lang": "de", "tgt_lang": "ar", "lemma": "invalid"} # قصير جداً
        ]
        aligned = batch_align_examples(raw_list)
        self.assertEqual(len(aligned), 1)

if __name__ == '__main__':
    unittest.main()
