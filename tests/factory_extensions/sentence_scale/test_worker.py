"""Synthetic fixtures and genuine-but-unapproved pilot: no production content receipts."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.factory_extensions.sentence_scale import worker


class SentenceScaleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.workspace = self.root / 'source'
        self.workspace.mkdir()
        self.out = self.root / 'out'
        self.db = self.root / 'checkpoint.sqlite'
        self.manifest = self.root / 'manifest.json'
        self.catalog = self.root / 'catalog.json'
        self.ledger = self.root / 'ledger.json'
        self.senses = self.root / 'senses.json'
        self.rules = self.root / 'rules.json'
        self.reviewers = self.root / 'reviewers.json'
        self.catalog.write_text(json.dumps({'schema_version': '1.0.0', 'languages':
            [{'id': c} for c in ['en', 'de', 'ar'] + [f'x{i:02d}' for i in range(97)]]}))
        self.ledger.write_text('{"schema_version":"1.0.0","sources":[]}')
        self.senses.write_text('{"schema_version":1,"senses":[]}')
        self.rules.write_text('{"schema_version":1,"rules":[]}')
        self.reviewers.write_text('{"schema_version":1,"reviewers":[]}')

    def row(self, sentence_id, text='Hello world.', language='en'):
        return {'schema_version': 1, 'source': {
            'source_id': 'demo', 'sentence_id': sentence_id,
            'origin_url': 'https://example.org/sentences/' + sentence_id,
            'publisher': 'Example Org', 'author': 'Publisher', 'license': 'CC0-1.0',
            'license_url': 'https://creativecommons.org/publicdomain/zero/1.0/',
            'attribution': 'Publisher https://example.org/sentences/' + sentence_id,
            'dataset_version': '2026-01', 'record_locator': sentence_id,
            'artifact_sha256': 'a' * 64, 'source_class': 'attested_corpus'},
            'language': language, 'text': text, 'context_id': 'greeting.hello',
            'situation': 'greetings', 'construction': 'positive', 'register': 'neutral',
            'politeness': 'unspecified', 'dialect': None,
            'sense_refs': [], 'grammar_refs': [],
            'sentence_cefr': None, 'word_cefr': None,
            'translations': [], 'privacy_class': 'public'}

    def invoke(self):
        return worker.process(self.manifest, self.workspace, self.db, self.out,
            catalog=self.catalog, ledger=self.ledger, senses=self.senses,
            rules=self.rules, reviewers=self.reviewers)

    def run_rows(self, rows):
        path = self.workspace / 'shard.jsonl'
        data = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).encode()
        path.write_bytes(data)
        self.manifest.write_text(json.dumps({'schema_version': 1, 'shards':
            [{'path': 'shard.jsonl', 'sha256': hashlib.sha256(data).hexdigest()}]}))
        return self.invoke()

    def test_empty_route05_ledger_blocks_source(self):
        report = self.run_rows([self.row('1')])
        self.assertEqual(report['totals']['accepted'], 0)
        self.assertEqual(report['totals']['requires_review'], 1)
        self.assertEqual(report['published'], 0)
        self.assertIn('route05_example_approval_missing',
            json.loads((self.out / 'candidates.jsonl').read_text())['reasons'])

    def test_checkpoint_idempotence(self):
        first = self.run_rows([self.row('1')])
        again = self.invoke()
        self.assertEqual(first['candidate_sha256'], again['candidate_sha256'])
        self.assertEqual(again['completed_shards'], 1)

    def test_duplicates_preserve_separate_source_ids(self):
        report = self.run_rows([self.row('1'), self.row('2')])
        self.assertEqual(report['totals']['requires_review'], 2)
        rows = [json.loads(line) for line in (self.out / 'candidates.jsonl').read_text().splitlines()]
        self.assertEqual(len({row['id'] for row in rows}), 2)
        self.assertTrue(all('exact_duplicate_requires_review' in row['reasons'] for row in rows))

    def test_duplicate_json_fields_are_malformed_not_content(self):
        raw = b'{"schema_version":1,"schema_version":1}\n'
        (self.workspace / 'shard.jsonl').write_bytes(raw)
        self.manifest.write_text(json.dumps({'schema_version': 1, 'shards':
            [{'path': 'shard.jsonl', 'sha256': hashlib.sha256(raw).hexdigest()}]}))
        report = self.invoke()
        self.assertEqual(report['malformed_unattributed'], 1)
        self.assertEqual(sum(report['totals'].values()), 0)

    def test_unknown_language_rejected_not_counted_as_registered(self):
        report = self.run_rows([self.row('1', language='zz')])
        self.assertEqual(report['totals']['rejected'], 1)
        self.assertEqual(report['unregistered_rejected'], 1)

    def test_tampered_shard_is_rejected_before_replay(self):
        self.run_rows([self.row('1')])
        (self.workspace / 'shard.jsonl').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            self.invoke()

    def test_canonical_hard_rejections_cannot_be_promoted(self):
        row = self.row('2')
        row['source']['source_class'] = 'reviewed_editorial'
        with patch.object(worker.canonical, 'validate',
                          return_value=('REJECTED', ['wrong_language_grammar_rule'], [])):
            status, reasons, _ = worker.validate_extended(row, {}, {}, {}, {}, {}, {'en'})
        self.assertEqual(status, 'REJECTED')
        self.assertIn('wrong_language_grammar_rule', reasons)

    def test_sentence_revision_is_held_and_old_payload_preserved(self):
        self.run_rows([self.row('1')])
        changed = self.row('1', text='Different sentence.')
        raw = (json.dumps(changed) + '\n').encode()
        (self.workspace / 'second.jsonl').write_bytes(raw)
        current = json.loads(self.manifest.read_text())
        current['shards'].append({'path': 'second.jsonl',
                                   'sha256': hashlib.sha256(raw).hexdigest()})
        self.manifest.write_text(json.dumps(current))
        report = self.invoke()
        saved = json.loads((self.out / 'candidates.jsonl').read_text())
        self.assertEqual(saved['text'], 'Hello world.')
        self.assertIn('immutable_sentence_revision', saved['reasons'])
        self.assertEqual(report['completed_shards'], 2)

    def test_mock_approved_attestations_still_never_publish(self):
        row = self.row('3')
        row['sense_refs'] = [{'sense_id': 'sense.mock', 'lexeme_id': 'lex.mock'}]
        text_hash = hashlib.sha256(row['text'].encode()).hexdigest()
        review = {'reviewer_id': 'reviewer.mock', 'sentence_sha256': text_hash,
                  'evidence_url': 'https://example.org/reviews/3'}
        row['review'] = {**review, 'decision': 'approved'}
        row['language_review'] = dict(review)
        row['annotation_review'] = dict(review)
        self.reviewers.write_text(json.dumps({'schema_version': 1, 'reviewers': [
            {'id': 'reviewer.mock', 'approved': True, 'languages': ['en']}]}))
        self.senses.write_text(json.dumps({'schema_version': 1, 'senses': [
            {'sense_id': 'sense.mock', 'lexeme_id': 'lex.mock', 'language': 'en'}]}))
        self.ledger.write_text(json.dumps({'schema_version': '1.0.0', 'sources': [{
            'source_id': 'demo', 'kind': 'examples',
            'publisher': 'Example Org', 'origin_url': 'https://example.org/sentences/',
            'dataset_version': '2026-01', 'status': 'APPROVED_FOR_REDISTRIBUTION',
            'retrieval': {'identity': 'fake-fixture', 'url': 'https://example.org/download',
                          'sha256': 'a' * 64},
            'license': {'id': 'CC0-1.0', 'evidence_sha256': 'b' * 64},
            'review': {'reviewer': 'reviewer.mock',
                       'decision_url': 'https://example.org/decisions/3'}
        }]}))
        with patch.object(worker.canonical, 'validate', return_value=('ACCEPTED', [], [])):
            result = self.run_rows([row])
        self.assertEqual(result['totals']['accepted'], 1)
        self.assertEqual(result['published'], 0)

    def test_null_translation_reviews_cannot_be_accepted(self):
        row = self.row('1')
        row['translations'] = [{
            'target_source_id': 'demo', 'target_sentence_id': '2',
            'target_language': 'de', 'direction': 'en_to_de',
            'evidence_url': 'https://example.org/links/1/2'
        }]
        row['translation_reviews'] = None
        report = self.run_rows([row])
        self.assertEqual(report['totals']['requires_review'], 1)
        candidate = json.loads((self.out / 'candidates.jsonl').read_text())
        self.assertIn('translation_equivalence_unverified', candidate['reasons'])

    def test_changed_hard_rejection_not_downgraded_to_review(self):
        self.run_rows([self.row('1')])
        changed = self.row('1', text='Different evidence.')
        payload = (json.dumps(changed) + '\n').encode()
        (self.workspace / 'second.jsonl').write_bytes(payload)
        manifest = json.loads(self.manifest.read_text())
        manifest['shards'].append({'path': 'second.jsonl',
                                   'sha256': hashlib.sha256(payload).hexdigest()})
        self.manifest.write_text(json.dumps(manifest))
        with patch.object(worker.canonical, 'validate',
                          return_value=('REJECTED', ['wrong_language_grammar_rule'], [])):
            result = self.invoke()
        self.assertEqual(result['totals']['rejected'], 1)

    def test_real_pilot_examples_without_approvals_are_not_accepted(self):
        pilot = Path('tools/source_examples/fixtures/pilot_tatoeba.jsonl')
        registry = Path('catalog/language_registry.v1.json')
        if not pilot.exists() or not registry.exists():
            self.skipTest('full GitHub checkout required')
        import shutil
        self.catalog = registry
        shutil.copyfile(pilot, self.workspace / 'pilot.jsonl')
        raw = (self.workspace / 'pilot.jsonl').read_bytes()
        self.manifest.write_text(json.dumps({'schema_version': 1, 'shards': [
            {'path': 'pilot.jsonl', 'sha256': hashlib.sha256(raw).hexdigest()}]}))
        result = self.invoke()
        self.assertEqual(result['totals'], {
            'accepted': 0, 'rejected': 0, 'requires_review': 5})
        self.assertEqual([result['languages'][lang]['requires_review'] for lang in
                          ('ar', 'de', 'en', 'es', 'fr')], [1] * 5)


    def test_revoked_source_grant_downgrades_cached_accepted_record(self):
        row = self.row('71')
        self.ledger.write_text(json.dumps({'schema_version': '1.0.0', 'sources': [{
            'source_id': 'demo', 'kind': 'examples', 'publisher': 'Example Org',
            'origin_url': 'https://example.org/sentences/', 'dataset_version': '2026-01',
            'status': 'APPROVED_FOR_REDISTRIBUTION',
            'retrieval': {'identity': 'mock', 'url': 'https://example.org/archive', 'sha256': 'a' * 64},
            'license': {'id': 'CC0-1.0', 'evidence_sha256': 'b' * 64},
            'review': {'decision_url': 'https://example.org/decision'}}]}))
        with patch.object(worker.canonical, 'validate', return_value=('ACCEPTED', [], [])), patch.object(worker, 'evidence', return_value=True):
            first = self.run_rows([row])
        self.assertEqual(first['totals']['accepted'], 1)
        self.ledger.write_text('{"schema_version":"1.0.0","sources":[]}')
        with patch.object(worker.canonical, 'validate', return_value=('ACCEPTED', [], [])):
            second = worker.process(self.manifest, self.workspace, self.db, self.out,
                catalog=self.catalog, ledger=self.ledger, senses=self.senses,
                rules=self.rules, reviewers=self.reviewers)
        self.assertEqual(second['totals']['accepted'], 0)
        self.assertEqual(second['totals']['requires_review'], 1)
        self.assertIn('route05_example_approval_missing',
                      json.loads((self.out / 'candidates.jsonl').read_text())['reasons'])

    def test_symlink_source_inside_workspace_is_not_immutable(self):
        original = self.workspace / 'actual.jsonl'
        raw = (json.dumps(self.row('72')) + '\n').encode()
        original.write_bytes(raw)
        (self.workspace / 'link.jsonl').symlink_to(original)
        self.manifest.write_text(json.dumps({'schema_version': 1, 'shards': [
            {'path': 'link.jsonl', 'sha256': hashlib.sha256(raw).hexdigest()}]}))
        with self.assertRaisesRegex(ValueError, 'symlink|unsafe'):
            worker.process(self.manifest, self.workspace, self.db, self.out,
                catalog=self.catalog, ledger=self.ledger, senses=self.senses,
                rules=self.rules, reviewers=self.reviewers)

    def test_oversized_record_does_not_prevent_next_valid_record(self):
        payload = b'x' * (worker.MAX_LINE + 4096) + b'\n' + (json.dumps(self.row('73')) + '\n').encode()
        path = self.workspace / 'shard.jsonl'
        path.write_bytes(payload)
        self.manifest.write_text(json.dumps({'schema_version': 1, 'shards': [
            {'path': 'shard.jsonl', 'sha256': hashlib.sha256(payload).hexdigest()}]}))
        result = worker.process(self.manifest, self.workspace, self.db, self.out,
            catalog=self.catalog, ledger=self.ledger, senses=self.senses,
            rules=self.rules, reviewers=self.reviewers)
        self.assertEqual(result['malformed_unattributed'], 1)
        self.assertEqual(result['totals']['requires_review'], 1)


    def test_process_closes_database_connection_after_processing(self):
        import sqlite3
        original_connect = sqlite3.connect
        closed = []

        class TrackedConnection(sqlite3.Connection):
            def close(self):
                closed.append(True)
                return super().close()

        def tracked_connect(*args, **kwargs):
            return original_connect(*args, factory=TrackedConnection, **kwargs)

        with patch.object(worker.sqlite3, 'connect', side_effect=tracked_connect):
            self.run_rows([self.row('96')])
        self.assertEqual(closed, [True])

    def test_duplicate_manifest_fields_are_rejected(self):
        self.manifest.write_text('{"schema_version":1,"shards":[],"shards":[]}')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            self.invoke()

    def test_duplicate_nested_source_ledger_keys_cannot_override_denial(self):
        self.ledger.write_text('{"schema_version":"1.0.0","sources":['
                               '{"source_id":"demo","kind":"examples",'
                               '"status":"BLOCKED_LICENSE","status":"APPROVED_FOR_REDISTRIBUTION"}]}')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            self.run_rows([self.row('94')])

    def test_duplicate_reviewer_roster_keys_are_rejected(self):
        self.reviewers.write_text('{"schema_version":1,"reviewers":['
                                  '{"id":"reviewer.demo","approved":false,'
                                  '"approved":true,"languages":["en"]}]}')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            self.run_rows([self.row('95')])


if __name__ == '__main__':
    unittest.main()
