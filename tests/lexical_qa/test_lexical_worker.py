import json
import os
import tempfile
import unicodedata
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.workers.lexical_worker import parse_lexical_record, run_lexical_worker

class TestLexicalWorker(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_unicode_nfc_normalization(self):
        # Decomposed NFD form: 'u' + combining diaeresis
        decomposed_word = "u\u0308ber"
        parsed = parse_lexical_record({'word': decomposed_word, 'senses': ['above']})
        # Assert normalized to single precomposed character
        self.assertEqual(parsed['term'], "über")
        self.assertEqual(parsed['term'], unicodedata.normalize('NFC', decomposed_word))

    def test_polysemous_senses_preserved_distinctly(self):
        raw = {
            'word': 'Bank',
            'pos': 'noun',
            'gender': 'feminin',
            'senses': ['bench (seat)', 'financial institution']
        }
        parsed = parse_lexical_record(raw)
        self.assertEqual(len(parsed['senses']), 2)
        self.assertEqual(parsed['senses'][0], 'bench (seat)')
        self.assertEqual(parsed['senses'][1], 'financial institution')

    def test_run_worker_produces_valid_output(self):
        src_path = os.path.join(self.temp_dir.name, "snapshot.json")
        dst_path = os.path.join(self.temp_dir.name, "out.json")

        with open(src_path, 'w') as f:
            json.dump({"seed_entries": [{"word": "Haus", "pos": "noun", "senses": ["house", "building"]}]}, f)

        ok, msg, count = run_lexical_worker(src_path, dst_path)
        self.assertTrue(ok)
        self.assertEqual(count, 1)

if __name__ == "__main__":
    unittest.main()
