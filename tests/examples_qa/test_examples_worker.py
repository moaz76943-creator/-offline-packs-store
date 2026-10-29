import json
import os
import tempfile
import unittest
import sys
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.workers.examples_worker import validate_and_parse_example, run_examples_worker

class TestExamplesWorker(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_directed_sentence_pair_parses(self):
        raw = {
            'term': 'Wasser',
            'sense_hint': 'beverage',
            'source_text': 'Das Wasser ist kalt.',
            'target_text': 'الماء بارد.'
        }
        res = validate_and_parse_example(raw, 'de', 'ar')
        self.assertIsNotNone(res)
        self.assertEqual(res['source_lang'], 'de')
        self.assertEqual(res['target_lang'], 'ar')
        self.assertEqual(res['source_sentence'], 'Das Wasser ist kalt.')
        self.assertEqual(res['target_sentence'], 'الماء بارد.')

    def test_single_word_fragments_rejected(self):
        raw = {
            'term': 'Buch',
            'source_text': 'Buch', # Not a valid sentence
            'target_text': 'كتاب'
        }
        res = validate_and_parse_example(raw, 'de', 'ar')
        self.assertIsNone(res)

    def test_run_examples_worker_writes_json(self):
        src_path = os.path.join(self.temp_dir.name, "seed.json")
        dst_path = os.path.join(self.temp_dir.name, "out.json")

        with open(src_path, 'w') as f:
            json.dump({
                'source_lang': 'de',
                'target_lang': 'ar',
                'sentence_pairs': [
                    {'term': 'gut', 'source_text': 'Das ist gut.', 'target_text': 'هذا جيد.'}
                ]
            }, f)

        ok, msg, count = run_examples_worker(src_path, dst_path)
        self.assertTrue(ok)
        self.assertEqual(count, 1)

if __name__ == "__main__":
    unittest.main()
