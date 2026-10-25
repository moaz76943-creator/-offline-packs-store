"""Offline SHA256 and rights-state regressions for retrieved corpus leads.

Real snapshots; never downloads anything or asserts legal permission.
"""
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / 'legal/ledger/evidence/retrieved-20261025'
EXPECTED = {
    'kaikki-de-prefix.jsonl': 'cce1e417e9482f1ef6d39472d42c1576e93d3c91aef5e795176a6fa978f9eefd',
    'kaikki-rawdata.html': 'e0314dbdd6ecedbf82d689767fe6631fb0cbcf521fd5b67ff02c742140c323c3',
    'tatoeba-eng-export-index.html': '9e8e97c90ecb125515b33c949a557bd9ad6572107a3ace977d69027f7c291850',
    'tatoeba-terms-of-use.html': 'f3e46eaac2d25bfacaab4e3cb834bd5252bb3df6367dd9da932bf46ec5ca2c22',
    'ud-english-ewt-LICENSE.txt': 'b3d1b0f4c6ae151f7eb78738f46ebd5ee140f8a7f76501ba26af123140d35ae7',
    'ud-english-ewt-stats.xml': 'fd787e647a84b286381bc2e30e0619a9b226f98e1ee20188d8cd357b168940f9',
    'wikidata-copyright-1523614187.txt': 'a74df271d6e2cceb81f71967fb180c66d08c33a670d14d8b64448ee9ef286396',
    'wikidata-lexemes-20261021-index.html': 'ea9bf8ac2911d63f0341c1e1360ecebc71657444c630d7aeb47e39ca326dd504',
    'wiktionary-copyrights-raw.txt': 'd184773bca30b7b23245a50d1d07c3d672b378a1e51757640e97b994b50c3689',
}


class RetrievedEvidenceTests(unittest.TestCase):
    def test_exact_retrieved_bytes_are_pinned(self):
        for name, digest in EXPECTED.items():
            with self.subTest(name=name):
                path = EVIDENCE / name
                self.assertTrue(path.is_file())
                self.assertFalse(path.is_symlink())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_kaikki_bounded_prefix_is_complete_jsonl_not_an_index(self):
        path = EVIDENCE / 'kaikki-de-prefix.jsonl'
        data = path.read_bytes()
        self.assertTrue(data.endswith(b'\\n'))
        self.assertGreater(len(data), 0)
        for line in data.splitlines():
            self.assertIsInstance(json.loads(line), dict)

    def test_research_candidates_never_populate_approved_ledger(self):
        research = json.loads((EVIDENCE / 'source-review-candidates.json').read_text())
        self.assertEqual(research['purpose'], 'REVIEW_ONLY_NOT_ADMISSION')
        self.assertEqual(research['admitted_sources'], 0)
        self.assertEqual(len(research['candidates']), 4)
        self.assertTrue(all(c['rights_classification'] == 'RIGHTS_REVIEW_REQUIRED'
                            and c['review_decision'] == 'NONE_INDEPENDENTLY_VERIFIED'
                            for c in research['candidates']))
        ledger = json.loads((ROOT / 'legal/ledger/sources.json').read_text())
        self.assertEqual(ledger['sources'], [])

    def test_three_metadata_only_sources_not_mislabeled_corpus(self):
        research = json.loads((EVIDENCE / 'source-review-candidates.json').read_text())
        metadata = [c for c in research['candidates']
                    if c['technical_classification'] == 'METADATA_ONLY_NOT_CORPUS']
        self.assertEqual(len(metadata), 3)
        for item in metadata:
            self.assertTrue(item['retrieval']['artifact_path'].endswith(('.html', '.xml')))


if __name__ == '__main__':
    unittest.main()
