import unittest
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.normalization.semantic_deduplicator import deduplicate_lexical_records

class TestSemanticDeduplicator(unittest.TestCase):
    def test_polysemous_word_preserves_distinct_senses(self):
        input_data = [
            {"term": "Schloss", "pos": "noun", "senses": ["castle, palace"], "source_id": "src_1"},
            {"term": "Schloss", "pos": "noun", "senses": ["lock (security device)"], "source_id": "src_2"},
        ]
        merged = deduplicate_lexical_records(input_data)
        self.assertEqual(len(merged), 1)
        # Both distinct concepts must be retained
        self.assertEqual(len(merged[0]['senses']), 2)
        self.assertIn("castle, palace", merged[0]['senses'])
        self.assertIn("lock (security device)", merged[0]['senses'])

    def test_identical_senses_deduplicated_with_merged_sources(self):
        input_data = [
            {"term": "Hund", "pos": "noun", "senses": ["dog"], "source_id": "kaikki"},
            {"term": "Hund", "pos": "noun", "senses": ["dog."], "source_id": "wiktionary"},
        ]
        merged = deduplicate_lexical_records(input_data)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]['senses']), 1)
        self.assertEqual(len(merged[0]['sources']), 2)
        self.assertIn("kaikki", merged[0]['sources'])
        self.assertIn("wiktionary", merged[0]['sources'])

    def test_pos_distinction_preserved(self):
        # 'lernen' as verb vs 'Lernen' as noun
        input_data = [
            {"term": "lernen", "pos": "verb", "senses": ["to learn"]},
            {"term": "lernen", "pos": "noun", "senses": ["learning process"]},
        ]
        merged = deduplicate_lexical_records(input_data)
        self.assertEqual(len(merged), 2)
        pos_set = {m['pos'] for m in merged}
        self.assertEqual(pos_set, {'verb', 'noun'})

if __name__ == "__main__":
    unittest.main()
