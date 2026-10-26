"""Contract-to-factory adapter regression: directed identity and no fake admission."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from factory_adapter import to_factory_jsonl
from validate import DirectedPairContractError
from tools.factory_extensions.directed_translation_scale.graph import each_candidate

HERE = Path(__file__).parent


def fixture():
    return json.loads((HERE / 'fixtures' / 'positive.json').read_text(encoding='utf-8'))


class FactoryAdapterTest(unittest.TestCase):
    def setUp(self):
        self.data = fixture()

    def test_factory_parser_reads_all_explicit_directions(self):
        payload = to_factory_jsonl(self.data)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'candidates.jsonl'
            path.write_bytes(payload)
            records = list(each_candidate(path, hashlib.sha256(payload).hexdigest()))
        pairs = self.data['directed_translations']
        self.assertEqual(len(records), len(pairs))
        self.assertEqual(
            {(r['translation_id'], r['from_sense_id'], r['to_sense_id'],
              r['source_language'], r['target_language']) for r in records},
            {(p['pair_id'], p['source_sense_id'], p['target_sense_id'],
              p['source_language'], p['target_language']) for p in pairs})
        self.assertTrue(all(r['source']['fixture_only'] for r in records))
        self.assertTrue(all('evidence' not in r for r in records))

    def test_language_swap_fails_before_factory(self):
        changed = copy.deepcopy(self.data)
        changed['directed_translations'][0]['source_language'] = 'fr'
        with self.assertRaisesRegex(DirectedPairContractError, 'source language disagrees'):
            to_factory_jsonl(changed)

    def test_publication_requires_independent_evidence(self):
        with self.assertRaisesRegex(DirectedPairContractError, 'publication requires independent'):
            to_factory_jsonl(self.data, publication=True)

    def test_external_attestation_only_never_fabricated(self):
        pair_id = self.data['directed_translations'][0]['pair_id']
        payload = to_factory_jsonl(self.data, attestation_by_pair={
            pair_id: {'kind': 'direct_sense_attestation', 'record_locator': 'external'}
        })
        rows = [json.loads(line) for line in payload.splitlines()]
        self.assertEqual(sum('evidence' in row for row in rows), 1)
        with self.assertRaisesRegex(DirectedPairContractError, 'unknown pair'):
            to_factory_jsonl(self.data, attestation_by_pair={'unknown.pair': {}})
        with self.assertRaisesRegex(DirectedPairContractError, 'must be an object'):
            to_factory_jsonl(self.data, attestation_by_pair={pair_id: 'self-approved'})

    def test_factory_line_budget_fails_closed(self):
        changed = copy.deepcopy(self.data)
        changed['directed_translations'][0]['text'] = 'x' * 70000
        with self.assertRaisesRegex(DirectedPairContractError, 'line budget'):
            to_factory_jsonl(changed)


if __name__ == '__main__':
    unittest.main()
