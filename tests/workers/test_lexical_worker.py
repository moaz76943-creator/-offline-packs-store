import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from tools.gha_factory.workers.lexical_worker import parse_kaikki_entry, normalize_text_nfc

class TestLexicalWorker(unittest.TestCase):
    def test_nfc_normalization(self):
        # حرف ü بصيغة NFD مجزأة مقابل NFC موحدة
        nfd_u = "u\u0308"
        self.assertEqual(normalize_text_nfc(nfd_u), "ü")

    def test_parse_multi_sense_entry(self):
        raw = {
            "word": "Buch",
            "pos": "noun",
            "sounds": [{"ipa": "/buːx/"}],
            "senses": [
                {"glosses": ["book (bound publication)"]},
                {"glosses": ["ledger, record"]},
                {"glosses": ["book (bound publication)"]} # مكرر يجب حذفه
            ]
        }
        parsed = parse_kaikki_entry(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["lemma"], "Buch")
        self.assertEqual(parsed["pos"], "noun")
        self.assertEqual(parsed["ipa"], "/buːx/")
        self.assertEqual(parsed["senses_count"], 2) # تم الحذف التكراري بنجاح

if __name__ == '__main__':
    unittest.main()
