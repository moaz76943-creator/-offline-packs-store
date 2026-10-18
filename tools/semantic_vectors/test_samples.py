"""Shipped fixtures: reproducible rights, integrity, semantic identity and 24px gates."""
import hashlib
import json
from pathlib import Path
import unittest

from compact import decode_token, render_svg

ROOT = Path(__file__).resolve().parents[2] / 'media' / 'semantic_vectors'


class ShippedFixtureTests(unittest.TestCase):
    def test_all_five_domains_hashes_evidence_and_readability(self):
        manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
        rights = json.loads((ROOT / 'provenance.json').read_text(encoding='utf-8'))
        source = rights['sources'][0]
        self.assertEqual(source['spdx_license'], 'CC0-1.0')
        self.assertEqual(hashlib.sha256((ROOT / source['evidence']).read_bytes()).hexdigest(), source['evidence_sha256'])
        bound = source['bound_source_sha256']
        self.assertEqual(len(bound), 5)
        self.assertEqual(len(set(bound)), 5)
        self.assertEqual({x['domain'] for x in manifest['assets']}, {'home', 'food', 'transport', 'education', 'healthcare'})
        self.assertEqual(len(manifest['assets']), 5)
        self.assertEqual(manifest['release_status'], 'decoder_pending')
        for asset in manifest['assets']:
            with self.subTest(concept=asset['concept_id']):
                raw = (ROOT / asset['token_path']).read_bytes()
                self.assertEqual(len(raw), asset['token_bytes'])
                self.assertLess(len(raw), 2048)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), asset['token_sha256'])
                self.assertEqual(hashlib.sha256((ROOT / asset['source_path']).read_bytes()).hexdigest(), asset['source_sha256'])
                self.assertIn(asset['source_sha256'], bound)
                self.assertEqual(asset['rights_evidence_sha256'], source['evidence_sha256'])
                self.assertEqual(len(asset['lexemes']), 3)
                self.assertEqual({x['language'] for x in asset['lexemes']}, {'en','de','ar'})
                self.assertTrue(all(x['sense_id'] == asset['sense_id'] for x in asset['lexemes']))
                shapes = decode_token(raw)
                self.assertGreaterEqual(len(shapes), 1)
                self.assertGreaterEqual(max(float(s[4]) for s in shapes), 2)
                for locale in ('en', 'de', 'ar'):
                    svg = render_svg(raw, asset['labels'][locale])
                    self.assertIn('role="img"', svg)
                    self.assertIn('viewBox="0 0 24 24"', svg)
                    self.assertIn('aria-label=', svg)


if __name__ == '__main__':
    unittest.main()
