import unittest
import sqlite3
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from tools.pack_conformance.validator import PackConformanceValidator, ConformanceError

class TestPackConformanceValidator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_db(self, name, setup_sql, insert_metadata=True, insert_lexicon=True, override_sort_key=None, corrupt=False):
        db_path = self.temp_path / name
        if corrupt:
            with open(db_path, 'wb') as f:
                f.write(b"not a sqlite db")
            return db_path

        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(setup_sql)
            if insert_metadata:
                conn.executescript("""
                    INSERT INTO metadata(key, value) VALUES
                    ('contract_version', '1.0.0'),
                    ('mapping_version', '2.0.0'),
                    ('document_id', 'doc-123');
                """)
            if insert_lexicon:
                source = json.dumps({"source_id": "src-1"})
                fields = json.dumps({"pos": "noun"})
                sort_key = override_sort_key if override_sort_key is not None else "hello"
                conn.execute("""
                    INSERT INTO lexicon (id, surface, part_of_speech, pos, direction, language_code, script, dialect, sort_key, cefr_level, frequency_rank, fields_json, source_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, ('lex-1', 'hello', 'noun', 'noun', 'ltr', 'en', 'Latn', None, sort_key, None, None, fields, source))

                # Insert into FTS only if FTS table is present
                try:
                    conn.execute("SELECT count(*) FROM lexicon_fts")
                    conn.execute("""
                        INSERT INTO lexicon_fts(rowid, surface, lemma, gloss, language_code)
                        VALUES (1, 'hello', 'hello', 'greeting', 'en')
                    """)
                except sqlite3.OperationalError:
                    pass
            conn.commit()
        finally:
            conn.close()

        return db_path

    def get_valid_ddl(self):
        return """
        PRAGMA foreign_keys=ON;
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE schema_migrations(version TEXT PRIMARY KEY, description TEXT NOT NULL);
        CREATE TABLE concepts(concept_id TEXT PRIMARY KEY);
        CREATE TABLE lexicon(
         id TEXT PRIMARY KEY, surface TEXT NOT NULL, part_of_speech TEXT NOT NULL,
         pos TEXT NOT NULL, direction TEXT NOT NULL, language_code TEXT NOT NULL,
         script TEXT NOT NULL, dialect TEXT, sort_key TEXT NOT NULL,
         cefr_level TEXT, frequency_rank INTEGER, fields_json TEXT NOT NULL,
         source_json TEXT NOT NULL
        );
        CREATE INDEX idx_lexicon_order ON lexicon(language_code,sort_key,id);
        CREATE INDEX idx_lexicon_surface ON lexicon(language_code,surface);
        CREATE TABLE senses(
         sense_id TEXT PRIMARY KEY, lexeme_id TEXT NOT NULL REFERENCES lexicon(id),
         concept_id TEXT NOT NULL REFERENCES concepts(concept_id), definition TEXT NOT NULL,
         payload_json TEXT NOT NULL
        );
        CREATE INDEX idx_senses_lexeme ON senses(lexeme_id,sense_id);
        CREATE TABLE translations(
         translation_id TEXT PRIMARY KEY, from_sense_id TEXT NOT NULL REFERENCES senses(sense_id),
         to_sense_id TEXT NOT NULL REFERENCES senses(sense_id), language_code TEXT NOT NULL,
         text TEXT NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE INDEX idx_translations_directed ON translations(from_sense_id,language_code,translation_id);
        CREATE TABLE examples(
         example_id TEXT PRIMARY KEY, sense_id TEXT NOT NULL REFERENCES senses(sense_id),
         lexeme_id TEXT NOT NULL REFERENCES lexicon(id), language_code TEXT NOT NULL,
         text TEXT NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE INDEX idx_examples_sense ON examples(sense_id,example_id);
        CREATE TABLE lexical_relations(
         relation_id TEXT PRIMARY KEY, from_lexeme_id TEXT NOT NULL REFERENCES lexicon(id),
         to_lexeme_id TEXT NOT NULL REFERENCES lexicon(id), kind TEXT NOT NULL,
         payload_json TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE lexicon_fts USING fts5(surface,lemma,gloss,language_code UNINDEXED,
         tokenize='unicode61 remove_diacritics 0');
        CREATE VIEW lexemes AS SELECT id,surface,part_of_speech,direction,fields_json FROM lexicon;
        """

    def test_valid_pack(self):
        db_path = self._create_db('valid.db', self.get_valid_ddl())
        validator = PackConformanceValidator(db_path)
        validator.validate() # Should not raise

    def test_corrupt_pack(self):
        db_path = self._create_db('corrupt.db', '', corrupt=True)
        validator = PackConformanceValidator(db_path)
        with self.assertRaises(ConformanceError) as ctx:
            validator.validate()
        self.assertIn("not a database", str(ctx.exception).lower())

    def test_empty_pack(self):
        db_path = self._create_db('empty.db', '', insert_metadata=False, insert_lexicon=False)
        validator = PackConformanceValidator(db_path)
        with self.assertRaises(ConformanceError) as ctx:
            validator.validate()
        self.assertIn('metadata table missing', str(ctx.exception))

    def test_missing_metadata(self):
        ddl = self.get_valid_ddl()
        db_path = self._create_db('no_meta.db', ddl, insert_metadata=False)
        validator = PackConformanceValidator(db_path)
        with self.assertRaises(ConformanceError) as ctx:
            validator.validate()
        self.assertIn('contract_version missing in metadata', str(ctx.exception))

    def test_mismatched_language(self):
        db_path = self._create_db('multi_lang.db', self.get_valid_ddl())
        conn = sqlite3.connect(db_path)
        source = json.dumps({"source_id": "src-1"})
        fields = json.dumps({"pos": "noun"})
        conn.execute("""
            INSERT INTO lexicon (id, surface, part_of_speech, pos, direction, language_code, script, dialect, sort_key, cefr_level, frequency_rank, fields_json, source_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('lex-2', 'hola', 'noun', 'noun', 'ltr', 'es', 'Latn', None, 'hola', None, None, fields, source))
        conn.commit()
        conn.close()

        validator = PackConformanceValidator(db_path)
        with self.assertRaises(ConformanceError) as ctx:
            validator.validate()
        self.assertIn('multiple language codes', str(ctx.exception))

    def test_invalid_nfkc_sort_key(self):
        db_path = self._create_db('bad_sort.db', self.get_valid_ddl(), override_sort_key='wrong')
        validator = PackConformanceValidator(db_path)
        with self.assertRaises(ConformanceError) as ctx:
            validator.validate()
        self.assertIn('Invalid sort_key', str(ctx.exception))

    def test_missing_fts_table(self):
        lines = self.get_valid_ddl().splitlines()
        # Remove CREATE VIRTUAL TABLE and the next line for tokenization
        new_lines = []
        skip = False
        for line in lines:
            if 'CREATE VIRTUAL TABLE lexicon_fts' in line:
                skip = True
                continue
            if skip:
                if ');' in line:
                    skip = False
                continue
            new_lines.append(line)
        ddl = "\n".join(new_lines)
        db_path = self._create_db('no_fts.db', ddl)
        validator = PackConformanceValidator(db_path)
        with self.assertRaises(ConformanceError) as ctx:
            validator.validate()
        self.assertIn("FTS5 index 'lexicon_fts' missing", str(ctx.exception))

if __name__ == '__main__':
    unittest.main()
