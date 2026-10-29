import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.compiler.deterministic_pack_builder import compile_deterministic_sqlite_pack

class TestDeterministicPackBuilder(unittest.TestCase):
    def test_bitwise_reproducible_compilation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pack_1 = os.path.join(tmp_dir, "test1.pack")
            pack_2 = os.path.join(tmp_dir, "test2.pack")

            sample_words = [
                {"lemma": "Buch", "pos": "noun", "cefr": "A1", "meaning": "كتاب"},
                {"lemma": "lernen", "pos": "verb", "cefr": "A1", "meaning": "يتعلم"}
            ]

            r1 = compile_deterministic_sqlite_pack(pack_1, "test_de_ar", "de", "ar", sample_words)
            r2 = compile_deterministic_sqlite_pack(pack_2, "test_de_ar", "de", "ar", sample_words)

            # التحقق من تطابق الهاش والحجم بدقة البايت
            self.assertEqual(r1["sha256"], r2["sha256"])
            self.assertEqual(r1["size_bytes"], r2["size_bytes"])
            self.assertEqual(r1["entry_count"], 2)

if __name__ == '__main__':
    unittest.main()
