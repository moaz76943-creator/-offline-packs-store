"""All examples are synthetic shape fixtures, NOT licensed lexical records."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('pilot5', Path(__file__).with_name('pipeline.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def fixture_source():
    return {'source_id': 'fixture.synthetic', 'origin_url': 'https://example.org/fixture',
            'publisher': 'Synthetic unit tests, not a corpus', 'dataset_version': 'fixture',
            'retrieval': {'identity': 'fixture', 'sha256': 'a' * 64},
            'license': {'id': 'CC-BY-SA-4.0'}}


class Pilot5Tests(unittest.TestCase):
    def test_five_languages_unicode_and_no_guessed_level(self):
        cases = [('de', 'Straße'), ('ar', 'كِتاب'), ('en', 'look up'),
                 ('es', 'árbol'), ('fr', "l'homme")]
        for lang, word in cases:
            with self.subTest(lang=lang):
                row = {'lang_code': lang, 'word': word, 'pos': 'verb' if lang == 'en' else 'noun',
                       'senses': [{'glosses': ['attested fixture gloss']}]}
                lex, senses = p.extract(row, lang, fixture_source(), 'line:1')
                self.assertEqual(lex['lemma'], word)
                self.assertEqual(lex['source']['record_locator'], 'line:1')
                self.assertEqual(lex['direction'], 'rtl' if lang == 'ar' else 'ltr')
                self.assertNotIn('levels', senses[0])
                if lang == 'en':
                    self.assertEqual(lex['pos'], 'multiword')

    def test_attested_morphology_and_ipa_only(self):
        row = {'lang_code': 'de', 'word': 'Haus', 'pos': 'noun',
               'tags': ['neuter'],
               'forms': [{'form': 'das', 'tags': ['article', 'definite', 'singular']},
                         {'form': 'Häuser', 'tags': ['plural']}],
               'sounds': [{'ipa': 'haʊ̯s'}],
               'senses': [{'glosses': ['building for living']}]}
        lex, _ = p.extract(row, 'de', fixture_source(), 'line:2')
        self.assertEqual(lex['morphology']['gender'], 'neuter')
        self.assertEqual(lex['morphology']['articles'][0]['surface'], 'das')
        self.assertEqual(lex['morphology']['inflections'][0]['surface'], 'Häuser')
        self.assertEqual(lex['pronunciations'][0]['notation'], 'ipa')
        self.assertNotEqual(p.stable('lex', 'de', 'Straße'), p.stable('lex', 'de', 'Strasse'))

    def test_language_mismatch_and_missing_senses_rejected(self):
        row = {'lang_code': 'es', 'word': 'casa', 'pos': 'noun',
               'senses': [{'glosses': ['house']}]}
        self.assertIsNone(p.extract(row, 'fr', fixture_source(), 'line:1'))
        self.assertIsNone(p.extract({**row, 'senses': []}, 'es', fixture_source(), 'line:1'))

    def test_deterministic_dedupe_and_original_bytes(self):
        row = {'lang_code': 'ar', 'word': 'عَلَم', 'pos': 'noun',
               'senses': [{'glosses': ['راية', 'راية', 'معرفة']}]}
        line = (json.dumps(row, ensure_ascii=False) + '\n').encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.jsonl'
            path.write_bytes(line + line + b'{}\n')
            doc, evidence, counts = p.ingest(path, 'ar', fixture_source())
            again, evidence2, counts2 = p.ingest(path, 'ar', fixture_source())
            self.assertEqual((doc, evidence, counts), (again, evidence2, counts2))
            self.assertEqual(len(doc['lexemes']), 1)
            self.assertEqual(len(doc['senses']), 2)
            self.assertEqual(counts, {'seen': 3, 'accepted': 1, 'accepted_senses': 2,
                                      'rejected': 1, 'duplicates': 1, 'limit_skipped': 0})
            self.assertEqual(evidence[0]['raw_line_utf8'].encode(), line)
            self.assertEqual(evidence[0]['raw_line_sha256'], hashlib.sha256(line).hexdigest())
            updated, _, counts3 = p.ingest(path, 'ar', fixture_source(), previous=doc)
            self.assertEqual(doc, updated)
            self.assertEqual(counts3['accepted'], 0)

    def test_same_lemma_separate_senses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.jsonl'
            rows = [{'lang_code': 'es', 'word': 'banco', 'pos': 'noun',
                     'senses': [{'glosses': [g]}]} for g in ('seat', 'financial institution')]
            path.write_text(''.join(json.dumps(x) + '\n' for x in rows))
            doc, evidence, counts = p.ingest(path, 'es', fixture_source())
            self.assertEqual((len(doc['lexemes']), len(doc['senses']), len(evidence)), (1, 2, 2))
            self.assertEqual(counts['accepted_senses'], 2)

    def test_missing_or_fake_license_proof_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / 'input.jsonl'
            input_path.write_text('{}\n')
            with self.assertRaises(ValueError):
                p.verify_source({'sources': []}, 'unknown', input_path, root)
            source = fixture_source()
            source.update({'kind': 'dictionary', 'status': 'APPROVED_FOR_REDISTRIBUTION',
                           'publisher': 'Unapproved fixture publisher',
                           'review': {'reviewer': 'fixture', 'decision_url': 'https://example.org/review'},
                           'retrieval': {'identity': 'fixture', 'url': 'https://example.org/input',
                                         'artifact_path': '../input.jsonl', 'sha256': p.file_sha(input_path)},
                           'license': {'id': 'CC-BY-SA-4.0',
                                       'evidence_url': 'https://example.org/license',
                                       'evidence_path': '../license', 'evidence_sha256': 'a' * 64}})
            with self.assertRaises(ValueError):
                p.verify_source({'sources': [source]}, 'fixture.synthetic', input_path, root)


if __name__ == '__main__':
    unittest.main()
