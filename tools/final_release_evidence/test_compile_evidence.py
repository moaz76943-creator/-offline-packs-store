import unittest
import os
import tempfile
import json
import gzip
from compile_evidence import compile_evidence, sha256sum

class TestCompileEvidence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.packs_dir = os.path.join(self.temp_dir.name, 'packs')
        os.makedirs(self.packs_dir)
        self.manifest_path = os.path.join(self.temp_dir.name, 'manifest.json')
        self.output_path = os.path.join(self.temp_dir.name, 'final_evidence.json')

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_mock_pack(self, lang_code, filename, content):
        path = os.path.join(self.packs_dir, filename)
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            json.dump(content, f)
        return sha256sum(path)

    def write_manifest(self, languages, expected_license='PUBLIC_DOMAIN_ZERO_COPYRIGHT'):
        manifest = {
            'intellectual_property_status': expected_license,
            'languages': languages
        }
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f)

    def test_release_ready(self):
        content = {
            "header": {
                "license": "Public Domain / Zero Copyright",
                "levels": ["A1", "A2"],
                "version": "1.0.0"
            },
            "domains": [1, 2],
            "lexicon": [1, 2, 3],
            "media": [1]
        }
        sha = self.create_mock_pack('de', 'de_pack.gz', content)

        langs = [{'code': f'l{i}', 'pack_file': None} for i in range(1, 100)]
        langs.append({
            'code': 'de',
            'pack_file': 'de_pack.gz',
            'sha256': sha
        })
        self.write_manifest(langs)

        evidence = compile_evidence(self.manifest_path, self.packs_dir, self.output_path)
        self.assertEqual(evidence['de']['state'], 'releaseReady')
        self.assertEqual(evidence['de']['details']['lexical_counts'], 3)
        self.assertEqual(evidence['de']['details']['media_identities'], 1)
        self.assertEqual(evidence['de']['details']['pack_version'], '1.0.0')
        self.assertEqual(evidence['de']['details']['source_license'], 'public domain / zero copyright')
        self.assertEqual(evidence['de']['details']['checksum_actual'], sha)

        self.assertEqual(evidence['l1']['state'], 'sourceMissing')
        self.assertEqual(len(evidence), 100)

    def test_source_missing(self):
        langs = [
            {'code': 'fr', 'pack_file': 'fr_pack.gz', 'sha256': 'fakehash'},
            {'code': 'es', 'pack_file': None}
        ]
        self.write_manifest(langs)
        evidence = compile_evidence(self.manifest_path, self.packs_dir, self.output_path)
        self.assertEqual(evidence['fr']['state'], 'sourceMissing')
        self.assertEqual(evidence['es']['state'], 'sourceMissing')

    def test_invalid_pack_hash(self):
        content = {"header": {"license": "Public Domain", "levels": ["A1"]}}
        _ = self.create_mock_pack('it', 'it_pack.gz', content)

        langs = [{'code': 'it', 'pack_file': 'it_pack.gz', 'sha256': 'wronghash'}]
        self.write_manifest(langs)
        evidence = compile_evidence(self.manifest_path, self.packs_dir, self.output_path)
        self.assertEqual(evidence['it']['state'], 'invalidPack')
        self.assertIn('checksum_actual', evidence['it']['details'])

    def test_license_blocked(self):
        content = {
            "header": {
                "license": "CC-BY-NC 4.0",
                "levels": ["A1"]
            },
            "domains": [1]
        }
        sha = self.create_mock_pack('ru', 'ru_pack.gz', content)
        langs = [{'code': 'ru', 'pack_file': 'ru_pack.gz', 'sha256': sha}]
        self.write_manifest(langs)
        evidence = compile_evidence(self.manifest_path, self.packs_dir, self.output_path)
        self.assertEqual(evidence['ru']['state'], 'licenseBlocked')

    def test_metadata_only(self):
        content = {
            "header": {
                "license": "Public Domain",
                "levels": []
            },
            "domains": [],
            "lexicon": []
        }
        sha = self.create_mock_pack('ja', 'ja_pack.gz', content)
        langs = [{'code': 'ja', 'pack_file': 'ja_pack.gz', 'sha256': sha}]
        self.write_manifest(langs)
        evidence = compile_evidence(self.manifest_path, self.packs_dir, self.output_path)
        self.assertEqual(evidence['ja']['state'], 'metadataOnly')

    def test_verified_only(self):
        # Missing levels or domains but has lexicon -> verified but not releaseReady
        content = {
            "header": {
                "license": "Public Domain",
                "levels": []
            },
            "domains": [],
            "lexicon": [1]
        }
        sha = self.create_mock_pack('ko', 'ko_pack.gz', content)
        langs = [{'code': 'ko', 'pack_file': 'ko_pack.gz', 'sha256': sha}]
        self.write_manifest(langs)
        evidence = compile_evidence(self.manifest_path, self.packs_dir, self.output_path)
        self.assertEqual(evidence['ko']['state'], 'verified')

    def test_invalid_pack_structure(self):
        path = os.path.join(self.packs_dir, 'bad.gz')
        with open(path, 'wb') as f:
            f.write(b'not a gzip')
        sha = sha256sum(path)

        langs = [{'code': 'ko', 'pack_file': 'bad.gz', 'sha256': sha}]
        self.write_manifest(langs)
        evidence = compile_evidence(self.manifest_path, self.packs_dir, self.output_path)
        self.assertEqual(evidence['ko']['state'], 'invalidPack')

    def test_atomic_failure_handling(self):
        with open(self.output_path, 'w') as f:
            f.write('{"old": "data"}')

        with self.assertRaises(Exception):
            compile_evidence('non_existent.json', self.packs_dir, self.output_path)

        with open(self.output_path, 'r') as f:
            content = f.read()
        self.assertEqual(content, '{"old": "data"}')

if __name__ == '__main__':
    unittest.main()
