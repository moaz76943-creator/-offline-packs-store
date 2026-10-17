import unittest
import os
import json
import gzip
import tempfile
import shutil
from pathlib import Path
from tools.final_release_evidence.compiler import (
    EvidenceCompiler,
    admitted_languages,
    manifest_pack_languages,
)

class TestEvidenceCompiler(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.packs_dir = os.path.join(self.test_dir, 'packs')
        os.makedirs(self.packs_dir)

        self.registry_path = os.path.join(self.test_dir, 'registry.json')
        self.manifest_path = os.path.join(self.test_dir, 'manifest.json')
        self.ledger_path = os.path.join(self.test_dir, 'sources.json')
        self.ledger_data = {'schema_version': '1.0.0', 'sources': []}

        self.registry_data = {
            'languages': [
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
            ],
            'packs': [],
        }
        self._write_inputs()

        self.compiler = EvidenceCompiler(
            registry_path=self.registry_path,
            manifest_path=self.manifest_path,
            packs_dir=self.packs_dir,
            ledger_path=self.ledger_path,
        )

    def _write_inputs(self):
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest_data, f)
        with open(self.ledger_path, 'w') as f:
            json.dump(self.ledger_data, f)

    def admit(self, code, status='APPROVED_FOR_REDISTRIBUTION', languages=None, publish=True):
        """Record an explicit source language and, by default, a manifest pack."""
        self.ledger_data['sources'].append({
            'source_id': f'src-{code}-{len(self.ledger_data["sources"])}',
            'status': status,
            'languages': [code] if languages is None else languages,
        })
        if publish:
            self.manifest_data['packs'].append({'id': code, 'language': code})
        self._write_inputs()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write_pack(self, filename, data):
        path = os.path.join(self.packs_dir, filename)
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            f.write(json.dumps(data) + '\n')
        return path

    def test_all_registered_ids_processed(self):
        # We have 5 registered IDs
        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)
        self.assertEqual(res['total_languages'], 5)
        self.assertEqual(len(res['languages']), 5)
        self.assertTrue(all(row['status'] == 'BLOCKED_DEPENDENCY' for row in res['languages'].values()))

    def test_missing_package(self):
        # No admitted source and no manifest pack: legacy languages[] cannot release.
        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)

        self.assertEqual(res['languages']['ar']['status'], 'BLOCKED_DEPENDENCY')
        self.assertEqual(res['languages']['es']['status'], 'BLOCKED_DEPENDENCY')
        self.assertEqual(res['languages']['ar']['packs'], [])

    def test_missing_package_after_admission(self):
        self.admit('ar')
        self.admit('es')
        self.manifest_data['languages'].append({'code': 'es', 'pack_file': 'es_core_a1.pack.gz'})
        self._write_inputs()
        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)
        self.assertEqual(res['languages']['ar']['status'], 'sourceMissing')
        self.assertEqual(res['languages']['es']['status'], 'sourceMissing')

    def test_invalid_signature(self):
        self.admit('ru')
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
        self.admit('de')
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
        self.admit('fr')
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
        self.admit('ar')
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
        self.compiler.load_manifest_document = lambda: (_ for _ in ()).throw(Exception("Force fail"))

        with self.assertRaises(Exception):
            self.compiler.compile(output_path)

        # Verify original still exists
        with open(output_path, 'r') as f:
            res = json.load(f)
            self.assertTrue(res.get("original"))

        # Verify no .tmp file left behind
        self.assertFalse(os.path.exists(output_path + '.tmp'))

    def test_on_disk_pack_without_admission_is_not_release_ready(self):
        pack_data = {"lang_code": "ar", "license": "CC0-1.0"}
        path = self.write_pack("ar_core_a1.pack.gz", pack_data)
        self.manifest_data['languages'][0]['sha256'] = self.compiler.compute_sha256(path)
        self._write_inputs()

        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)
        row = res['languages']['ar']
        self.assertEqual(row['status'], 'BLOCKED_DEPENDENCY')
        self.assertEqual(row['packs'], [])
        self.assertFalse(any(pack.get('valid') for pack in row['packs']))

    def test_unscoped_or_partial_admission_stays_blocked(self):
        self.ledger_data['sources'].append({
            'source_id': 'unscoped',
            'status': 'APPROVED_FOR_REDISTRIBUTION',
        })
        self.ledger_data['sources'].append({
            'source_id': 'review',
            'status': 'REVIEW_REQUIRED',
            'languages': ['ar'],
        })
        self.manifest_data['packs'].append({'id': 'ar', 'language': 'ar'})
        self._write_inputs()
        pack_data = {"lang_code": "ar", "license": "CC0-1.0"}
        path = self.write_pack("ar_core_a1.pack.gz", pack_data)
        self.manifest_data['languages'][0]['sha256'] = self.compiler.compute_sha256(path)
        self._write_inputs()

        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)
        self.assertEqual(res['languages']['ar']['status'], 'BLOCKED_DEPENDENCY')
        self.assertNotIn('ar', admitted_languages(self.ledger_data))

    def test_source_without_manifest_pack_stays_blocked(self):
        self.admit('ar', publish=False)
        pack_data = {"lang_code": "ar", "license": "CC0-1.0"}
        path = self.write_pack("ar_core_a1.pack.gz", pack_data)
        self.manifest_data['languages'][0]['sha256'] = self.compiler.compute_sha256(path)
        self._write_inputs()
        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)
        self.assertIn('ar', admitted_languages(self.ledger_data))
        self.assertNotIn('ar', manifest_pack_languages(self.manifest_data))
        self.assertEqual(res['languages']['ar']['status'], 'BLOCKED_DEPENDENCY')

    def test_release_ready_only_with_admitted_source_and_manifest_pack(self):
        self.admit('ar')
        pack_data = {"lang_code": "ar", "license": "CC0-1.0"}
        path = self.write_pack("ar_core_a1.pack.gz", pack_data)
        self.manifest_data['languages'][0]['sha256'] = self.compiler.compute_sha256(path)
        self._write_inputs()
        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as f:
            res = json.load(f)
        self.assertEqual(res['languages']['ar']['status'], 'releaseReady')
        self.assertTrue(res['languages']['ar']['packs'][0]['valid'])
        self.assertEqual(res['languages']['ru']['status'], 'BLOCKED_DEPENDENCY')

    def test_committed_evidence_requires_admitted_source_and_manifest_pack(self):
        root = Path(__file__).resolve().parents[2]
        evidence = json.loads((root / 'tools/final_release_evidence/release_evidence.json').read_text())
        ledger = json.loads((root / 'legal/ledger/sources.json').read_text())
        manifest = json.loads((root / 'manifest.json').read_text())
        admitted = admitted_languages(ledger)
        published = manifest_pack_languages(manifest)
        languages = evidence['languages']
        self.assertEqual(evidence['total_languages'], len(languages))
        for code, row in languages.items():
            packs = row.get('packs') or []
            if row.get('status') == 'releaseReady' or any(pack.get('valid') for pack in packs):
                self.assertIn(code, admitted, f'{code} is release-ready without an admitted source')
                self.assertIn(code, published, f'{code} is release-ready without a manifest pack')
        if not ledger.get('sources') and not manifest.get('packs'):
            ready = [code for code, row in languages.items() if row.get('status') == 'releaseReady']
            self.assertEqual(ready, [])
            self.assertTrue(all(row.get('status') == 'BLOCKED_DEPENDENCY' for row in languages.values()))
            self.assertTrue(all(row.get('packs') == [] for row in languages.values()))

if __name__ == '__main__':
    unittest.main()
