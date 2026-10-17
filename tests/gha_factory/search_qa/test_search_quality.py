"""Read-only synthetic search quality regression tests; no licensed production data."""
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.gha_factory.search_qa import audit


class SearchQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "search.sqlite"

    def make_db(self, language="de", surfaces=()):
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                PRAGMA user_version=2;
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT INTO metadata VALUES('mapping_version','2.0.0');
                INSERT INTO metadata VALUES('contract_version','1.0.0');
                CREATE TABLE lexicon(id TEXT PRIMARY KEY,surface TEXT,language_code TEXT);
                CREATE VIRTUAL TABLE lexicon_fts USING fts5(
                    surface,lemma,gloss,language_code UNINDEXED,
                    tokenize='unicode61 remove_diacritics 0');
            """)
            for index, surface in enumerate(surfaces):
                identity = f"lex.{index:03}"
                db.execute('INSERT INTO lexicon VALUES(?,?,?)',
                           (identity, surface, language))
                rowid = db.execute('SELECT rowid FROM lexicon WHERE id=?',
                                   (identity,)).fetchone()[0]
                db.execute(
                    'INSERT INTO lexicon_fts(rowid,surface,lemma,gloss,language_code) '
                    'VALUES(?,?,?,?,?)',
                    (rowid, surface, surface, 'fixtureterm', language))
        return self.path

    def test_exact_before_prefix_before_fts_and_stable_tie_break(self):
        self.make_db("de", ("ab", "a", "abc", "zz"))
        with sqlite3.connect(self.path) as db:
            expected = [
                ("lex.001", "EXACT"),
                ("lex.000", "PREFIX"),
                ("lex.002", "PREFIX"),
            ]
            self.assertEqual(audit.probe_search(db, "de", "a"), expected)
            self.assertEqual(
                audit.probe_search(db, "de", "fixtureterm"),
                [(f"lex.{i:03}", "FTS5") for i in range(4)])
            db.execute("PRAGMA reverse_unordered_selects=ON")
            self.assertEqual(audit.probe_search(db, "de", "a"), expected)
            self.assertEqual(len({ident for ident, tier in expected}), len(expected))

    def test_dedup_does_not_hide_prefix_rows_behind_exact_rows(self):
        self.make_db("de", ("cat",) * 10 + ("cater", "cathedral"))
        with sqlite3.connect(self.path) as db:
            results = audit.probe_search(db, "de", "cat")
        self.assertEqual(len(results), 12)
        self.assertEqual([tier for _, tier in results],
                         ["EXACT"] * 10 + ["PREFIX"] * 2)
        self.assertEqual(len({ident for ident, tier in results}), 12)

    def test_unicode_distinctness_and_script_aware_exact_prefix(self):
        cases = [
            ("de", ("Straße", "Strasse", "Äpfel"), "Straße", [("lex.000", "EXACT")]),
            ("tr", ("İstanbul", "istanbul", "Işık", "ışık"), "İ",
             [("lex.000", "PREFIX")]),
            ("ar", ("عَلَم", "علم", "بَيْت"), "علم", [("lex.001", "EXACT")]),
            ("ja", ("日本語", "日本", "かな"), "日本",
             [("lex.001", "EXACT"), ("lex.000", "PREFIX")]),
            ("ko", ("한글", "한국"), "한", [("lex.000", "PREFIX"), ("lex.001", "PREFIX")]),
            ("th", ("ภาษาไทย", "ภาษา"), "ภาษา",
             [("lex.001", "EXACT"), ("lex.000", "PREFIX")]),
        ]
        for language, surfaces, query, expected in cases:
            with self.subTest(language=language):
                self.make_db(language, surfaces)
                before = hashlib.sha256(self.path.read_bytes()).hexdigest()
                with sqlite3.connect(self.path) as db:
                    self.assertEqual(audit.probe_search(db, language, query),
                                     expected)
                report = audit.check_sqlite(self.path, language)
                self.assertEqual(report["ranked_samples"], len(surfaces))
                self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())
                self.path.unlink()

    def test_turkish_i_and_arabic_diacritics_are_not_silently_folded(self):
        self.make_db("tr", ("Istanbul", "İstanbul", "istanbul", "ıstanbul"))
        with sqlite3.connect(self.path) as db:
            for query, expected in (("I", "lex.000"), ("İ", "lex.001"),
                                    ("i", "lex.002"), ("ı", "lex.003")):
                self.assertEqual(audit.probe_search(db, "tr", query),
                                 [(expected, "PREFIX")])
        self.path.unlink()
        self.make_db("ar", ("عَلَم", "علم"))
        with sqlite3.connect(self.path) as db:
            self.assertEqual(audit.probe_search(db, "ar", "علم"),
                             [("lex.001", "EXACT")])

    def test_non_nfc_tail_record_rejected_without_writing(self):
        self.make_db("de", tuple(f"Wort{i:02}" for i in range(15)))
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE lexicon SET surface=? WHERE id='lex.014'", ("A\u0308pfel",))
            db.execute("UPDATE lexicon_fts SET surface=?,lemma=? WHERE rowid=15",
                       ("A\u0308pfel", "A\u0308pfel"))
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(audit.AuditError, "non-NFC"):
            audit.check_sqlite(self.path, "de")
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_empty_tail_record_rejected_even_when_fts_aligned(self):
        self.make_db("de", tuple(f"Wort{i:02}" for i in range(15)))
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE lexicon SET surface='' WHERE id='lex.014'")
            db.execute("UPDATE lexicon_fts SET surface='' WHERE rowid=15")
        with self.assertRaisesRegex(audit.AuditError, "invalid.*lexical surface"):
            audit.check_sqlite(self.path, "de")

    def test_null_lexical_identity_rejected(self):
        self.make_db("de", ("Wort",))
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE lexicon SET id=NULL WHERE rowid=1")
        with self.assertRaisesRegex(audit.AuditError, "stable lexical identity"):
            audit.check_sqlite(self.path, "de")

    def test_probe_rejects_unbounded_or_non_nfc_input(self):
        self.make_db("de", ("Wort",))
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(audit.AuditError):
                audit.probe_search(db, "de", "A\u0308pfel")
            with self.assertRaises(audit.AuditError):
                audit.probe_search(db, "de", "a" * (audit.MAX_SEARCH_TERM_BYTES + 1))
            with self.assertRaises(audit.AuditError):
                audit.probe_search(db, "de", "Wort", limit=0)

    def test_structurally_fake_fts_table_rejected(self):
        self.make_db("de", ("Wort",))
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TABLE lexicon_fts")
            db.execute("CREATE TABLE lexicon_fts(surface,lemma,gloss,language_code)")
            db.execute("INSERT INTO lexicon_fts VALUES('Wort','Wort','fixtureterm','de')")
        with self.assertRaisesRegex(audit.AuditError, "FTS5 virtual"):
            audit.check_sqlite(self.path, "de")


if __name__ == "__main__":
    unittest.main()
