import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.content_filter.cultural_policy_filter import is_content_culturally_compliant

class TestCulturalPolicyFilter(unittest.TestCase):
    def test_clean_educational_entry(self):
        entry = {
            "lemma": "lernen",
            "tags": ["education", "verb"],
            "glosses": ["to study, to acquire knowledge"]
        }
        compliant, violations = is_content_culturally_compliant(entry)
        self.assertTrue(compliant)
        self.assertEqual(violations, [])

    def test_vulgar_entry_blocked(self):
        entry = {
            "lemma": "inappropriate_term",
            "tags": ["slur"],
            "glosses": ["a derogatory slur"]
        }
        compliant, violations = is_content_culturally_compliant(entry)
        self.assertFalse(compliant)
        self.assertTrue(len(violations) >= 2)

if __name__ == '__main__':
    unittest.main()
