import unittest
import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from tools.gha_factory.content_filter.cultural_policy_filter import (
    is_content_admissible,
    filter_dataset
)

class TestCulturalPolicyFilter(unittest.TestCase):
    def test_innocent_words_with_substrings_pass(self):
        # 'Klasse', 'Pass', 'Assistent' must never be blocked by false-positive substring matching
        samples = [
            {"term": "Klasse", "senses": ["classroom", "school grade"]},
            {"term": "Pass", "senses": ["passport", "mountain pass"]},
            {"term": "Assistent", "senses": ["assistant", "aide"]},
            {"term": "مساعد", "senses": ["assistant"]},
        ]
        for s in samples:
            ok, msg = is_content_admissible(s)
            self.assertTrue(ok, f"False positive detected on innocent word: {s['term']} ({msg})")

    def test_prohibited_lexical_tags_blocked(self):
        vulgar_entry = {
            "term": "vulgar_slang_term",
            "tags": ["vulgar", "slang"],
            "senses": ["offensive meaning"]
        }
        ok, msg = is_content_admissible(vulgar_entry)
        self.assertFalse(ok)
        self.assertIn("FILTERED_BY_TAG", msg)

    def test_prohibited_terms_in_sentences_blocked(self):
        sentence_entry = {
            "term": "schlecht",
            "source_sentence": "Du Arschloch, geh weg!",
            "target_sentence": "ابتعد من هنا!"
        }
        ok, msg = is_content_admissible(sentence_entry)
        self.assertFalse(ok)
        self.assertIn("FILTERED_BY_PATTERN", msg)

if __name__ == "__main__":
    unittest.main()
