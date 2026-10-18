"""Offline synthetic CJK regression suite; examples are test fixtures, not corpus claims."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
from linguistic_extensions.cjk.engine import Segmenter, evaluate_partition, validate_unit


def unit(lang, surface, ident, sense="sense-1", readings=None, features=None):
    return {
        "language": lang, "surface": surface, "unit_id": ident,
        "sense_id": sense, "source_id": "synthetic-fixture",
        "source_revision": "v1", "script": {"zh": "Han", "ja": "Jpan", "ko": "Hang"}[lang],
        "pos": "noun", "approved": True, "readings": readings or [],
        "features": features or [],
    }


def reading(lang, sense="sense-1", value="reading"):
    return {
        "reading_id": "reading-1", "language": lang, "sense_id": sense,
        "text": value, "system": "source-attested", "source_id": "synthetic-fixture",
    }


class CJKTests(unittest.TestCase):
    def test_chinese_multichar_longest_match(self):
        parser = Segmenter("zh", [unit("zh", "银行", "bank"),
                                  unit("zh", "行", "single")])
        tokens = parser.segment("银行。")
        self.assertEqual([(t.raw, t.status) for t in tokens],
                         [("银行", "accepted"), ("。", "unmatched")])
        self.assertEqual(tokens[0].units[0]["unit_id"], "bank")

    def test_combining_mark_stays_with_the_unattested_cluster(self):
        parser = Segmenter("zh", [unit("zh", "漢", "han")])
        tokens = parser.segment("漢\u0301")
        self.assertEqual([(t.raw, t.status) for t in tokens], [("漢\u0301", "unmatched")])
        attested = Segmenter("zh", [unit("zh", "漢\u0301", "marked")])
        self.assertEqual(attested.segment("漢\u0301")[0].status, "accepted")

    def test_chinese_no_unapproved_single_han_translation(self):
        self.assertEqual(Segmenter("zh", [unit("zh", "银行", "bank")])
                         .segment("行")[0].status, "unmatched")

    def test_japanese_mixed_scripts_and_attested_inflection(self):
        parser = Segmenter("ja", [unit("ja", "食べます", "polite"),
                                  unit("ja", "食べ", "stem")])
        self.assertEqual(parser.segment("食べます、")[0].units[0]["unit_id"], "polite")
        self.assertEqual(parser.segment("カタカナ")[0].status, "unmatched")

    def test_korean_hangul_composition_nfc(self):
        parser = Segmenter("ko", [unit("ko", "학교", "school")])
        self.assertEqual(parser.segment("학교")[0].units[0]["unit_id"], "school")

    def test_homographs_keep_senses_separate(self):
        a = unit("ja", "はし", "bridge", "bridge-sense",
                 [reading("ja", "bridge-sense", "はし")])
        b = unit("ja", "はし", "chopsticks", "chopsticks-sense",
                 [reading("ja", "chopsticks-sense", "はし")])
        self.assertEqual([x["unit_id"] for x in Segmenter("ja", [a, b])
                         .segment("はし")[0].units], ["bridge", "chopsticks"])

    def test_cross_language_readings_rejected(self):
        record = unit("zh", "銀行", "bank", readings=[reading("ja")])
        with self.assertRaisesRegex(ValueError, "cross-language"):
            validate_unit(record)

    def test_framework_without_evidence_rejected(self):
        record = unit("ja", "学生", "student")
        record["level"] = {"framework": "JLPT", "value": "N5"}
        with self.assertRaisesRegex(ValueError, "evidence"):
            validate_unit(record)

    def test_unapproved_and_implicit_variants_rejected(self):
        record = unit("zh", "汉语", "han")
        record["approved"] = False
        with self.assertRaises(ValueError):
            validate_unit(record)
        record["approved"] = True
        record["variants"] = ["漢語"]
        with self.assertRaises(ValueError):
            validate_unit(record)

    def test_morphology_requires_evidence(self):
        record = unit("ko", "먹었습니다", "past",
                      features=[{"kind": "speech_level", "value": "formal"}])
        with self.assertRaises(ValueError):
            validate_unit(record)

    def test_limits(self):
        with self.assertRaises(ValueError):
            Segmenter("ko", [unit("ko", "학교", "one")], max_units=0)
        with self.assertRaises(ValueError):
            Segmenter("zh", [unit("zh", "超" * 33, "huge")])
        with self.assertRaises(ValueError):
            Segmenter("ja", [unit("ja", "日", "same"), unit("ja", "本", "same")])

    def test_punctuation_and_unicode_safety(self):
        parser = Segmenter("ja", [unit("ja", "東京", "tokyo")])
        self.assertEqual([s.status for s in parser.segment("東京。!")],
                         ["accepted", "unmatched", "unmatched"])
        with self.assertRaises(ValueError):
            parser.segment("\ud800")

    def test_report_real_counts(self):
        report = evaluate_partition("zh", [unit("zh", "中文", "zh")], ["中文。"])
        self.assertEqual(report["accepted_distinct_units"], 1)
        self.assertEqual(report["dictionary_units"], 1)
        self.assertEqual(report["unmatched_segments"], 1)
        self.assertEqual(len(report["input_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
