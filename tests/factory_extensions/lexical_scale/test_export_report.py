"""Synthetic-only Route06 candidate export and 100-language coverage checks."""
import json
from pathlib import Path

from test_adapter import AdapterTests


class ExportReportTests(AdapterTests):
    def test_bounded_route06_fragments_and_no_synthesized_translations(self):
        from tools.factory_extensions.lexical_scale.export import export_fragments
        self.run_ingestion()
        manifest = export_fragments(self.db, 'ar', self.root / 'candidates', max_lexemes=1)
        self.assertEqual(len(manifest['fragments']), 2)
        self.assertEqual(manifest['accepted_senses'], 4)
        for entry in manifest['fragments']:
            d = json.loads((self.root / 'candidates' / entry['path']).read_text())
            self.assertEqual(d['translations'], [])
            self.assertEqual(d['contract_version'], '1.0.0')
            self.assertEqual(len(d['lexemes']), 1)
        with self.assertRaisesRegex(ValueError, 'OUTPUT_EXISTS'):
            export_fragments(self.db, 'ar', self.root / 'candidates')

    def test_canonical_coverage_unprocessed_vs_zero_and_incomplete_receipt(self):
        from tools.factory_extensions.lexical_scale.report import coverage
        report = coverage(self.root, [])
        self.assertEqual(report['registered_languages'], 100)
        self.assertEqual(report['measured_languages'], 0)
        self.assertIsNone(report['languages']['de']['accepted_lexemes'])
        receipt = self.run_ingestion()
        data = coverage(self.root, [receipt])
        self.assertEqual(data['measured_languages'], 1)
        self.assertEqual(data['languages']['ar']['accepted_lexemes'], 2)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            coverage(self.root, [receipt, receipt])

    def test_alternate_shard_layouts_are_conflicts_not_sums(self):
        from tools.factory_extensions.lexical_scale.report import coverage
        base = {
            'status': 'REVIEW_REQUIRED', 'language': 'ar', 'source_id': 'fixture.lex',
            'source_sha256': 'ab' * 32, 'complete': True, 'source_rows': 4,
            'accepted_lexemes': 2, 'accepted_senses': 2, 'rejected_rows': 0,
            'coverage_gaps': [],
        }
        single = dict(base, shard=0, shards=1, checkpoint_id='layout-1')
        split = [dict(base, shard=index, shards=2, checkpoint_id=f'layout-2-{index}')
                 for index in range(2)]
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_SHARD_LAYOUT'):
            coverage(self.root, [single, *split])
