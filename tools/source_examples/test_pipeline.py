"""Contract-level positive and negative tests (synthetic content is never published)."""
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.source_examples.pipeline import ingest, search


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'index.sqlite'
        self.out = self.root / 'bundles'
        self.ledger = self.root / 'ledger.json'
        self.senses = self.root / 'senses.json'
        self.rules = self.root / 'rules.json'
        self.reviewers = self.root / 'reviewers.json'
        self.ledger.write_text(json.dumps({'schema_version': 1, 'sources': [{'source_id': 'sample', 'publisher': 'TestPublisher', 'license': 'CC-BY-2.0-FR', 'redistribution_approved': True, 'origin_prefix': 'https://example.org/sentences/'}]}))
        self.senses.write_text(json.dumps({'schema_version': 1, 'senses': [{'sense_id': 'en.greeting.1', 'language': 'en', 'lexeme_id': 'greet'}]}))
        self.rules.write_text(json.dumps({'schema_version': 1, 'rules': [{'rule_id': 'en.greeting.form', 'language': 'en', 'explanation': 'Use a greeting formula.', 'allowed_cases': [], 'allowed_agreements': []}]}))
        self.reviewers.write_text(json.dumps({'schema_version': 1, 'reviewers': [{'id': 'linguist1', 'languages': ['en'], 'approved': True}]}))

    def record(self, text='Hello!', sid='13', context='social.greet'):
        row = {
            'schema_version': 1, 'source': {'source_id': 'sample', 'sentence_id': sid, 'origin_url': 'https://example.org/sentences/' + sid,
                'publisher': 'TestPublisher', 'author': 'UserA', 'license': 'CC-BY-2.0-FR',
                'license_url': 'https://creativecommons.org/licenses/by/2.0/fr/',
                'attribution': 'UserA, TestPublisher, https://example.org/sentences/' + sid},
            'language': 'en', 'text': text, 'context_id': context, 'situation': 'greetings',
            'construction': 'positive', 'register': 'neutral', 'politeness': 'unspecified', 'dialect': None,
            'sense_refs': [{'sense_id': 'en.greeting.1', 'lexeme_id': 'greet'}], 'grammar_refs': [
                {'rule_id': 'en.greeting.form'}], 'sentence_cefr': None, 'word_cefr': None,
            'translations': [], 'privacy_class': 'public',
        }
        row['review'] = {'decision': 'approved', 'reviewer_id': 'linguist1', 'evidence_url': 'https://example.org/review/13',
                         'sentence_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
        return row

    def run_rows(self, rows):
        src = self.root / 'input.jsonl'
        src.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
        return ingest(src, self.db, self.out, self.ledger, self.senses, self.rules, self.reviewers)

    def test_approved_record_is_bundled_and_indexed(self):
        result = self.run_rows([self.record()])
        self.assertEqual(result['totals'], {'accepted': 1, 'rejected': 0, 'requires_review': 0})
        with gzip.open(self.out / 'accepted' / 'en.jsonl.gz', 'rt', encoding='utf-8') as handle:
            exported = json.loads(next(handle))
        self.assertEqual(exported['text'], 'Hello!')
        self.assertEqual(exported['grammar'][0]['explanation'], 'Use a greeting formula.')
        self.assertEqual(len(search(self.db, 'en', 'greetings', 'en.greeting.1', 10)), 1)

    def test_no_review_proof_never_accepted(self):
        row = self.record()
        row.pop('review')
        self.assertEqual(self.run_rows([row])['totals']['requires_review'], 1)

    def test_unsupported_source_license_is_rejected(self):
        row = self.record()
        row['source']['license'] = 'unknown'
        self.assertEqual(self.run_rows([row])['totals']['rejected'], 1)

    def test_wrong_script_rejected(self):
        row = self.record(text='مرحبا!')
        self.assertEqual(self.run_rows([row])['totals']['rejected'], 1)

    def test_duplicate_preserved_and_flagged(self):
        rows = [self.record(sid='13'), self.record(sid='14')]
        rows[1]['source']['origin_url'] = 'https://example.org/sentences/14'
        rows[1]['source']['attribution'] = 'UserA, TestPublisher, https://example.org/sentences/14'
        self.assertEqual(self.run_rows(rows)['totals'], {'accepted': 0, 'rejected': 0, 'requires_review': 2})
        self.assertEqual(self.run_rows(rows)['totals'], {'accepted': 0, 'rejected': 0, 'requires_review': 2})

    def test_distinct_contexts_not_collapsed(self):
        row = self.record(sid='14', context='travel.greet')
        self.assertEqual(self.run_rows([self.record(), row])['totals']['accepted'], 2)

    def test_translation_targets_require_actual_local_evidence(self):
        row = self.record()
        row['translations'] = [{'target_source_id': 'sample', 'target_sentence_id': '999', 'target_language': 'es',
                                'direction': 'en_to_es', 'evidence_url': 'https://example.org/sentences/13'}]
        self.assertEqual(self.run_rows([row])['totals']['requires_review'], 1)

    def test_stable_id_during_incremental_ingestion(self):
        self.run_rows([self.record()])
        first = search(self.db, 'en', 'greetings', 'en.greeting.1', 10)[0]['id']
        row2 = self.record(text='Hello there!')
        self.assertEqual(self.run_rows([row2])['totals']['requires_review'], 1)
        self.assertEqual(first, search(self.db, 'en', 'greetings', 'en.greeting.1', 10, statuses=('REQUIRES_REVIEW',))[0]['id'])

    def test_grammatical_case_mismatch_rejected(self):
        row = self.record()
        row['grammar_refs'] = [{'rule_id': 'en.greeting.form', 'case': 'accusative'}]
        self.assertEqual(self.run_rows([row])['totals']['rejected'], 1)

    def test_rtl_combining_mark_preserved_review(self):
        row = self.record(text='مَرْحَبًا!', sid='15')
        row['language'] = 'ar'
        row['sense_refs'] = []
        row['grammar_refs'] = []
        row.pop('review')
        result = self.run_rows([row])
        self.assertEqual(result['totals']['requires_review'], 1)
        self.assertTrue((self.out / 'requires_review.jsonl').read_text().find('مَرْحَبًا!') > -1)

    def test_empty_and_untrusted_private_data_rejected(self):
        rows = [self.record(text=' '), self.record(sid='17')]
        rows[1]['privacy_class'] = 'learner_conversation'
        self.assertEqual(self.run_rows(rows)['totals']['rejected'], 2)

    def test_deterministic_bundles(self):
        self.run_rows([self.record()])
        before = (self.out / 'accepted' / 'en.jsonl.gz').read_bytes()
        self.run_rows([self.record()])
        self.assertEqual(before, (self.out / 'accepted' / 'en.jsonl.gz').read_bytes())


if __name__ == '__main__':
    unittest.main()

class PilotFixtureTests(unittest.TestCase):
    def test_real_sourced_fixtures_remain_unpublished_without_external_approvals(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            fixtures = Path(__file__).parent / 'fixtures' / 'pilot_tatoeba.jsonl'
            result = ingest(fixtures, root / 'index.sqlite', root / 'out')
            self.assertEqual(result['batch']['upserted'], 5)
            self.assertEqual(result['totals'], {'accepted': 0, 'rejected': 0, 'requires_review': 5})
            self.assertEqual(len((root / 'out' / 'requires_review.jsonl').read_text().splitlines()), 5)
            self.assertFalse(any((root / 'out' / 'accepted').glob('*.gz')))
            languages = {json.loads(line)['language'] for line in fixtures.read_text().splitlines()}
            self.assertEqual(languages, {'de', 'ar', 'en', 'es', 'fr'})

class NativeContractTests(unittest.TestCase):
    def test_native_empty_legal_ledger_does_not_grant_approval(self):
        from tools.source_examples.pipeline import load_registry
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / 'sources.json'
            f.write_text('{"schema_version":"1.0.0","sources":[]}')
            self.assertEqual(load_registry(f, 'sources'), {})

    def test_native_lexical_fixture_only_senses_are_not_approved(self):
        from tools.source_examples.pipeline import load_registry
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / 'lexical.json'
            f.write_text(json.dumps({'contract_version':'1.0.0', 'lexemes':[
                {'lexeme_id':'l1', 'language':'de', 'source':{'fixture_only': True, 'publication_approved': False}}],
                'senses':[{'sense_id':'s1', 'lexeme_id':'l1', 'source':{'fixture_only':True,'publication_approved':False}}]}))
            self.assertEqual(load_registry(f, 'senses'), {})
