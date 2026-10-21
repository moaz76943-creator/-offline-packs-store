"""Synthetic-only security and resumability tests: no distributable corpus."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.factory_extensions.lexical_scale import adapter as a


def sha(data):
    return hashlib.sha256(data).hexdigest()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for folder in ('catalog', 'legal/ledger', 'evidence'):
            (self.root / folder).mkdir(parents=True)
        languages = [dict(id=f'q{i:02d}', default_script='Latn') for i in range(100)]
        languages[0] = dict(id='de', default_script='Latn')
        languages[1] = dict(id='ar', default_script='Arab')
        (self.root / 'catalog/language_registry.v1.json').write_text(json.dumps({
            'schema_version': '1.0.0', 'languages': languages}), encoding='utf-8')
        self.rows = [
            {'lang_code': 'ar', 'word': 'عَلَم', 'pos': 'noun', 'etymology_number': 1,
             'senses': [{'glosses': ['راية', 'إشارة'], 'tags': ['formal']},
                        {'glosses': ['راية'], 'tags': ['regional']}],
             'forms': [{'form': 'أعلام', 'tags': ['plural']}], 'sounds': [{'ipa': '/ʕalam/'}]},
            {'lang_code': 'ar', 'word': 'عَلَم', 'pos': 'noun', 'etymology_number': 2,
             'senses': [{'glosses': ['معرفة']}]},
            {'lang_code': 'ar', 'word': 'fake', 'pos': 'noun',
             'senses': [{'glosses': ['swapped script']}]},
            {'lang_code': 'de', 'word': 'Baum', 'pos': 'noun',
             'senses': [{'glosses': ['Baum']}]}]
        self.write_rows(self.rows)
        (self.root / 'evidence/license.txt').write_text('TEST rights', encoding='utf-8')
        (self.root / 'evidence/review.txt').write_text('TEST approved fixture', encoding='utf-8')
        self.source = {
            'source_id': 'fixture.lex', 'kind': 'dictionary',
            'origin_url': 'https://example.org/synthetic', 'publisher': 'TEST-ONLY',
            'dataset_version': 'fixture-v1', 'status': 'APPROVED_FOR_REDISTRIBUTION',
            'alterations': ['Synthetic test fixture only'],
            'retrieval': {'identity': 'fixture-v1', 'url': 'https://example.org/synthetic.jsonl',
                          'date': '2026-10-13', 'artifact_path': 'evidence/data.jsonl',
                          'sha256': sha((self.root / 'evidence/data.jsonl').read_bytes())},
            'license': {'id': 'CC0-1.0', 'evidence_url': 'https://example.org/rights',
                        'evidence_path': 'evidence/license.txt',
                        'evidence_sha256': sha((self.root / 'evidence/license.txt').read_bytes())},
            'review': {'reviewer': 'TEST ONLY', 'decision_url': 'https://example.org/review',
                       'evidence_path': 'evidence/review.txt',
                       'evidence_sha256': sha((self.root / 'evidence/review.txt').read_bytes())}}
        self.ledger([self.source])
        self.db = self.root / 'checkpoint.sqlite'

    def write_rows(self, rows):
        (self.root / 'evidence/data.jsonl').write_bytes(b''.join(
            (json.dumps(x, ensure_ascii=False) + '\n').encode() if isinstance(x, dict) else x
            for x in rows))

    def ledger(self, entries):
        (self.root / 'legal/ledger/sources.json').write_text(json.dumps({
            'schema_version': '1.0.0', 'sources': entries}), encoding='utf-8')

    def run_ingestion(self, language='ar', shard=0, shards=1, batch=1, limit=None):
        return a.ingest(self.root, 'fixture.lex', language, self.db, shard=shard,
                        shards=shards, batch=batch, max_rows=limit)

    def test_unapproved_source_blocks_without_state(self):
        self.ledger([])
        with self.assertRaisesRegex(ValueError, 'BLOCKED_SOURCE'):
            self.run_ingestion()
        self.assertFalse(self.db.exists())

    def test_review_proof_and_snapshot_tampering_block(self):
        (self.root / 'evidence/review.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'BLOCKED_SOURCE'):
            self.run_ingestion()
        self.assertFalse(self.db.exists())

    def test_multisense_homograph_unicode_and_morphology(self):
        report = self.run_ingestion()
        self.assertTrue(report['complete'])
        self.assertEqual(report['source_rows'], 4)
        self.assertEqual(report['accepted_lexemes'], 2)
        self.assertEqual(report['accepted_senses'], 4)
        self.assertEqual(report['rejected_rows'], 2)
        with sqlite3.connect(self.db) as cx:
            entries = [json.loads(x[0]) for x in cx.execute('select payload from lexemes')]
            senses = [json.loads(x[0]) for x in cx.execute('select payload from senses')]
        self.assertEqual({x['lemma'] for x in entries}, {'عَلَم'})
        self.assertEqual(len({x['lexeme_id'] for x in entries}), 2)
        self.assertTrue(any(x['morphology']['inflections'][0]['surface'] == 'أعلام'
                            for x in entries if 'morphology' in x))
        self.assertTrue(all(x['source']['record_locator'].startswith('line:') for x in senses))
        self.assertTrue(all(x['source']['publication_approved'] is False for x in senses))

    def test_resume_and_replay_counts_are_identical(self):
        first = self.run_ingestion(limit=1)
        self.assertFalse(first['complete'])
        second = self.run_ingestion(limit=2)
        self.assertFalse(second['complete'])
        third = self.run_ingestion()
        self.assertTrue(third['complete'])
        fourth = self.run_ingestion()
        self.assertEqual(third, fourth)
        self.assertEqual(third['accepted_lexemes'], 2)
        with self.assertRaisesRegex(ValueError, 'CHECKPOINT_IDENTITY'):
            self.run_ingestion(shard=0, shards=2)

    def test_partition_disjoint_language_and_stable_ids(self):
        identities = []
        for shard in range(3):
            db = self.root / f'shard{shard}.sqlite'
            a.ingest(self.root, 'fixture.lex', 'ar', db, shard=shard, shards=3)
            with sqlite3.connect(db) as cx:
                identities.append({x[0] for x in cx.execute('select id from lexemes')})
        self.assertTrue(all(not identities[i] & identities[j]
                            for i in range(3) for j in range(i + 1, 3)))
        self.assertEqual(len(set.union(*identities)), 2)

    def test_synthetic_100_languages_can_validate_metadata(self):
        registry = a.language_registry(self.root)
        self.assertEqual(len(registry), 100)
        self.assertIn('q99', registry)
        with self.assertRaisesRegex(ValueError, 'BLOCKED_LANGUAGE'):
            self.run_ingestion('xyz')

    def test_malformed_utf8_duplicates_and_framing_rejected(self):
        raw = [b'{"word":"one","word":"two"}\n', b'\xff\n', b'{broken}\n']
        self.write_rows(raw + self.rows[:1])
        self.source['retrieval']['sha256'] = sha((self.root / 'evidence/data.jsonl').read_bytes())
        self.ledger([self.source])
        result = self.run_ingestion()
        self.assertEqual(result['rejected_rows'], 3)
        self.assertEqual(result['accepted_lexemes'], 1)
        self.assertEqual(result['accepted_senses'], 3)

    def test_malformed_input_counted_once_across_four_shards(self):
        self.write_rows([b'{bad}\n'] + self.rows[:1])
        self.source['retrieval']['sha256'] = sha((self.root / 'evidence/data.jsonl').read_bytes())
        self.ledger([self.source])
        results = [a.ingest(self.root, 'fixture.lex', 'ar', self.root / f'bad-{i}.sqlite',
                            shard=i, shards=4) for i in range(4)]
        self.assertEqual(sum(x['rejected_rows'] for x in results), 1)
        self.assertEqual(sum(x['accepted_lexemes'] for x in results), 1)

    def test_romanization_and_foreign_script_are_not_inflections(self):
        row = dict(self.rows[0])
        row['forms'] = [
            {'form': 'أعلام', 'tags': ['plural']},
            {'form': 'alam', 'tags': ['romanization']},
            {'form': 'flag', 'tags': ['plural']},
            {'form': 'عَلَم', 'tags': ['romanization']},
        ]
        self.write_rows([row])
        self.source['retrieval']['sha256'] = sha((self.root / 'evidence/data.jsonl').read_bytes())
        self.ledger([self.source])
        self.run_ingestion()
        with sqlite3.connect(self.db) as cx:
            lexemes = [json.loads(item[0]) for item in cx.execute('select payload from lexemes')]
        surfaces = [form['surface'] for lex in lexemes
                    for form in lex.get('morphology', {}).get('inflections', [])]
        self.assertEqual(surfaces, ['أعلام'])

    def test_detect_uniform_counts_as_warning_only(self):
        d = {x: {'accepted_lexemes': 2500, 'source_rows': 3200} for x in ('ar','de','en','es')}
        self.assertIn('SUSPICIOUS_UNIFORM_COUNTS', a.quality_flags(d))
        d['es']['accepted_lexemes'] = 2501
        self.assertNotIn('SUSPICIOUS_UNIFORM_COUNTS', a.quality_flags(d))


if __name__ == '__main__':
    unittest.main()
