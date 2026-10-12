"""Atomic incremental media publishing, rights and sense-bound identity."""
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from build import BuildError, build_pack
from compact import decode_token

SVG = '<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" fill="none" stroke="#172b4d" stroke-width="2"/></svg>'


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.src = self.base / 'sources'
        self.src.mkdir()
        (self.src / 'box.svg').write_text(SVG, encoding='utf-8')
        self.meta = self.base / 'concepts.json'
        self.rights = self.base / 'provenance.json'
        self.out = self.base / 'fixtures'
        self.manifest = self.base / 'manifest.json'
        self.item = {'concept_id': 'concept.test.box.object', 'sense_id': 'test.box.object.1', 'domain': 'home', 'source': 'box.svg', 'source_version': '1.0.0', 'license_id': 'cc0-project-original-v1', 'labels': {'en': 'Box', 'de': 'Kiste'}, 'lexemes': [{'language': 'en', 'lemma': 'box', 'sense_id': 'test.box.object.1'}]}
        self.meta.write_text(json.dumps({'schema_version': 1, 'concepts': [self.item]}), encoding='utf-8')
        self.prov = {'license_id': 'cc0-project-original-v1', 'spdx_license': 'CC0-1.0', 'origin_type': 'project_original', 'author': 'Project original illustration author', 'source_version': '1.0.0', 'evidence': 'AUTHORSHIP.md', 'rights_confirmed': True}
        (self.base / 'AUTHORSHIP.md').write_text('Original vector source declaration.', encoding='utf-8')
        self.prov['evidence_sha256'] = hashlib.sha256((self.base / 'AUTHORSHIP.md').read_bytes()).hexdigest()
        self.rights.write_text(json.dumps({'schema_version':1, 'sources': [self.prov]}), encoding='utf-8')

    def build(self):
        return build_pack(self.meta, self.rights, self.src, self.out, self.manifest, '2026-10-12')

    def test_manifest_hashes_and_incremental_idempotence(self):
        doc = self.build()
        item = doc['assets'][0]
        token = (self.base / item['token_path']).read_bytes()
        self.assertEqual(hashlib.sha256(token).hexdigest(), item['token_sha256'])
        self.assertLess(len(token), 2048)
        self.assertEqual(len(decode_token(token)), 1)
        self.assertFalse(doc['decoder_compatibility']['verified'])
        self.assertEqual(doc['release_status'], 'decoder_pending')
        original = self.manifest.read_bytes()
        self.assertEqual(doc, self.build())
        self.assertEqual(original, self.manifest.read_bytes())

    def test_rejects_unlicensed_and_preserves_existing(self):
        self.build()
        original = self.manifest.read_bytes()
        self.prov['rights_confirmed'] = False
        self.rights.write_text(json.dumps({'schema_version':1, 'sources':[self.prov]}), encoding='utf-8')
        with self.assertRaises(BuildError):
            self.build()
        self.assertEqual(original, self.manifest.read_bytes())

    def test_rejects_sense_alias_collision_and_changed_approved_bytes(self):
        self.build()
        original = self.manifest.read_bytes()
        (self.src / 'box.svg').write_text(SVG.replace('width="16"', 'width="15"'), encoding='utf-8')
        with self.assertRaises(BuildError):
            self.build()
        self.assertEqual(original, self.manifest.read_bytes())
        (self.src / 'box.svg').write_text(SVG, encoding='utf-8')
        wrong = dict(self.item, lexemes=[{'language': 'en', 'lemma': 'box', 'sense_id': 'different.sense'}])
        self.meta.write_text(json.dumps({'schema_version':1, 'concepts':[wrong]}), encoding='utf-8')
        with self.assertRaises(BuildError):
            self.build()
        self.assertEqual(original, self.manifest.read_bytes())

    def test_adds_one_concept_without_replacing_old_token(self):
        old = self.build()['assets'][0]
        (self.src / 'bag.svg').write_text(SVG.replace('width="16"', 'width="15"'), encoding='utf-8')
        second = dict(self.item, concept_id='concept.test.bag.object', sense_id='test.bag.object.1', source='bag.svg', lexemes=[{'language':'en', 'lemma':'bag', 'sense_id':'test.bag.object.1'}])
        self.meta.write_text(json.dumps({'schema_version':1, 'concepts':[self.item, second]}), encoding='utf-8')
        current = self.build()
        self.assertEqual(next(x for x in current['assets'] if x['concept_id'] == old['concept_id']), old)
        self.assertEqual(len(current['assets']), 2)


if __name__ == '__main__':
    unittest.main()
