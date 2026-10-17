import unittest
import os
import json
import gzip
import tempfile
import shutil
from tools.final_release_evidence.compiler import EvidenceCompiler

class TestEvidenceCompiler(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.packs_dir = os.path.join(self.test_dir, 'packs')
        os.makedirs(self.packs_dir)

        self.registry_path = os.path.join(self.test_dir, 'registry.json')
        self.manifest_path = os.path.join(self.test_dir, 'manifest.json')

        self.registry_data = {
            'languages': [{'id': f'lang_{i}'} for i in range(1, 96)] + [
                {'id': 'ar'}, {'id': 'ru'}, {'id': 'de'}, {'id': 'fr'}, {'id': 'es'}
            ]
        }
        with open(self.registry_path, 'w') as f:
            json.dump(self.registry_data, f)

        self.manifest_data = {
            'languages': [
                {'code': 'ar', 'pack_file': 'ar_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'ru', 'pack_file': 'ru_core_a1.pack.gz', 'sha256': 'ru_hash'},
                {'code': 'de', 'pack_file': 'de_core_a1.pack.gz', 'sha256': 'de_hash'},
                {'code': 'fr', 'pack_file': 'fr_core_a1.pack.gz', 'sha256': 'fr_hash'},
            ]
        }
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest_data, f)

        self.compiler = EvidenceCompiler(
            registry_path=self.registry_path,
            manifest_path=self.manifest_path,
            packs_dir=self.packs_dir
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write_pack(self, filename, data):
        path = os.path.join(self.packs_dir, filename)
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            f.write(json.dumps(data) + '\n')
        return path

    def test_all_registered_ids_processed(self):
        # We have 100 registered IDs
        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)
        self.assertEqual(res['total_languages'], 100)
        self.assertEqual(len(res['languages']), 100)

    def test_missing_package(self):
        # No packs exist yet
        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)

        # 'ar' is in manifest but missing
        self.assertEqual(res['languages']['ar']['status'], 'sourceMissing')
        # 'es' is not in manifest and missing
        self.assertEqual(res['languages']['es']['status'], 'metadataOnly')

    def test_invalid_signature(self):
        # Hash mismatch
        pack_data = {"lang_code": "ru", "license": "CC0-1.0"}
        p = self.write_pack("ru_core_a1.pack.gz", pack_data)

        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)

        self.assertEqual(res['languages']['ru']['status'], 'invalidPack')
        self.assertTrue(any("Hash mismatch" in r for r in res['languages']['ru']['reasons']))

    def test_stale_evidence(self):
        # Same as invalid signature for this case, if the file changes but manifest has old hash
        # We test changing source version (simulate by wrong hash)
        pack_data = {"lang_code": "de", "license": "CC0-1.0"}
        p = self.write_pack("de_core_a1.pack.gz", pack_data)

        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)

        self.assertEqual(res['languages']['de']['status'], 'invalidPack')
        self.assertTrue(any("Hash mismatch" in r for r in res['languages']['de']['reasons']))

    def test_incomplete_licensing(self):
        pack_data = {"lang_code": "fr", "license": "Private / Proprietary"}
        p = self.write_pack("fr_core_a1.pack.gz", pack_data)
        # Update manifest to match hash
        actual_hash = self.compiler.compute_sha256(p)
        self.manifest_data['languages'][3]['sha256'] = actual_hash
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest_data, f)

        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)

        self.assertEqual(res['languages']['fr']['status'], 'licenseBlocked')

    def test_mismatched_identities(self):
        pack_data = {"lang_code": "es", "license": "CC0-1.0"}
        p = self.write_pack("ar_core_a1.pack.gz", pack_data)
        actual_hash = self.compiler.compute_sha256(p)
        self.manifest_data['languages'][0]['sha256'] = actual_hash
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest_data, f)

        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)

        self.assertEqual(res['languages']['ar']['status'], 'invalidPack')
        self.assertTrue(any("Mismatched internal lang_code" in r for r in res['languages']['ar']['reasons']))

    def test_fail_closed_no_overwrite(self):
        # Create a valid original out file
        output_path = os.path.join(self.test_dir, 'out.json')
        with open(output_path, 'w') as f:
            json.dump({"original": True}, f)

        # Break the compiler temporarily to throw exception during compile
        self.compiler.load_manifest = lambda: (_ for _ in ()).throw(Exception("Force fail"))

        with self.assertRaises(Exception):
            self.compiler.compile(output_path)

        # Verify original still exists
        with open(output_path, 'r') as f:
            res = json.load(f)
            self.assertTrue(res.get("original"))

        # Verify no .tmp file left behind
        self.assertFalse(os.path.exists(output_path + '.tmp'))

if __name__ == '__main__':
    unittest.main()
