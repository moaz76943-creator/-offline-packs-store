import unittest
import os
import json
import hashlib
import tempfile
import shutil
from pathlib import Path

import jsonschema

from tools.final_release_evidence.compiler import (
    EvidenceCompiler,
    admitted_languages,
    manifest_pack_languages,
)

ROOT = Path(__file__).resolve().parents[2]
LEDGER_SCHEMA = json.loads((ROOT / 'legal/ledger/schema.json').read_text())
DIGEST = 'ab' * 32


def schema_source(source_id, status='APPROVED_FOR_REDISTRIBUTION', dataset_version='1.0.0'):
    """A ledger source the canonical schema accepts. It does not name a language."""
    return {
        'source_id': source_id,
        'kind': 'dictionary',
        'origin_url': 'https://example.com/sources/' + source_id,
        'publisher': 'Example Publisher',
        'author': 'Example Author',
        'dataset_version': dataset_version,
        'retrieval': {
            'identity': source_id,
            'url': 'https://example.com/sources/' + source_id,
            'date': '2026-01-01',
            'artifact_path': 'evidence/' + source_id + '.bin',
            'sha256': DIGEST,
        },
        'license': {
            'id': 'CC0-1.0',
            'evidence_url': 'https://example.com/licenses/' + source_id,
            'evidence_path': 'evidence/' + source_id + '.license',
            'evidence_sha256': DIGEST,
        },
        'status': status,
        'alterations': ['normalized for the offline pack'],
        'review': {
            'reviewer': 'reviewer',
            'decision_url': 'https://github.com/moaz76943-creator/-offline-packs-store/pull/355',
        },
    }


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
                {'id': 'ar'}, {'id': 'ru'}, {'id': 'de'}, {'id': 'fr'}, {'id': 'es'}, {'id': 'l0'}, {'id': 'l1'}, {'id': 'l2'}, {'id': 'l3'}, {'id': 'l4'}, {'id': 'l5'}, {'id': 'l6'}, {'id': 'l7'}, {'id': 'l8'}, {'id': 'l9'}, {'id': 'l10'}, {'id': 'l11'}, {'id': 'l12'}, {'id': 'l13'}, {'id': 'l14'}, {'id': 'l15'}, {'id': 'l16'}, {'id': 'l17'}, {'id': 'l18'}, {'id': 'l19'}, {'id': 'l20'}, {'id': 'l21'}, {'id': 'l22'}, {'id': 'l23'}, {'id': 'l24'}, {'id': 'l25'}, {'id': 'l26'}, {'id': 'l27'}, {'id': 'l28'}, {'id': 'l29'}, {'id': 'l30'}, {'id': 'l31'}, {'id': 'l32'}, {'id': 'l33'}, {'id': 'l34'}, {'id': 'l35'}, {'id': 'l36'}, {'id': 'l37'}, {'id': 'l38'}, {'id': 'l39'}, {'id': 'l40'}, {'id': 'l41'}, {'id': 'l42'}, {'id': 'l43'}, {'id': 'l44'}, {'id': 'l45'}, {'id': 'l46'}, {'id': 'l47'}, {'id': 'l48'}, {'id': 'l49'}, {'id': 'l50'}, {'id': 'l51'}, {'id': 'l52'}, {'id': 'l53'}, {'id': 'l54'}, {'id': 'l55'}, {'id': 'l56'}, {'id': 'l57'}, {'id': 'l58'}, {'id': 'l59'}, {'id': 'l60'}, {'id': 'l61'}, {'id': 'l62'}, {'id': 'l63'}, {'id': 'l64'}, {'id': 'l65'}, {'id': 'l66'}, {'id': 'l67'}, {'id': 'l68'}, {'id': 'l69'}, {'id': 'l70'}, {'id': 'l71'}, {'id': 'l72'}, {'id': 'l73'}, {'id': 'l74'}, {'id': 'l75'}, {'id': 'l76'}, {'id': 'l77'}, {'id': 'l78'}, {'id': 'l79'}, {'id': 'l80'}, {'id': 'l81'}, {'id': 'l82'}, {'id': 'l83'}, {'id': 'l84'}, {'id': 'l85'}, {'id': 'l86'}, {'id': 'l87'}, {'id': 'l88'}, {'id': 'l89'}, {'id': 'l90'}, {'id': 'l91'}, {'id': 'l92'}, {'id': 'l93'}, {'id': 'l94'}
            ]
        }
        with open(self.registry_path, 'w') as f:
            json.dump(self.registry_data, f)

        self.manifest_data = {
            'languages': [
                {'code': 'ar', 'pack_file': 'ar_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'ru', 'pack_file': 'ru_core_a1.pack.gz', 'sha256': 'ru_hash'},
                {'code': 'l0', 'pack_file': 'l0_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l1', 'pack_file': 'l1_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l2', 'pack_file': 'l2_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l3', 'pack_file': 'l3_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l4', 'pack_file': 'l4_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l5', 'pack_file': 'l5_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l6', 'pack_file': 'l6_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l7', 'pack_file': 'l7_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l8', 'pack_file': 'l8_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l9', 'pack_file': 'l9_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l10', 'pack_file': 'l10_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l11', 'pack_file': 'l11_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l12', 'pack_file': 'l12_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l13', 'pack_file': 'l13_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l14', 'pack_file': 'l14_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l15', 'pack_file': 'l15_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l16', 'pack_file': 'l16_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l17', 'pack_file': 'l17_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l18', 'pack_file': 'l18_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l19', 'pack_file': 'l19_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l20', 'pack_file': 'l20_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l21', 'pack_file': 'l21_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l22', 'pack_file': 'l22_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l23', 'pack_file': 'l23_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l24', 'pack_file': 'l24_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l25', 'pack_file': 'l25_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l26', 'pack_file': 'l26_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l27', 'pack_file': 'l27_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l28', 'pack_file': 'l28_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l29', 'pack_file': 'l29_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l30', 'pack_file': 'l30_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l31', 'pack_file': 'l31_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l32', 'pack_file': 'l32_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l33', 'pack_file': 'l33_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l34', 'pack_file': 'l34_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l35', 'pack_file': 'l35_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l36', 'pack_file': 'l36_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l37', 'pack_file': 'l37_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l38', 'pack_file': 'l38_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l39', 'pack_file': 'l39_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l40', 'pack_file': 'l40_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l41', 'pack_file': 'l41_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l42', 'pack_file': 'l42_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l43', 'pack_file': 'l43_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l44', 'pack_file': 'l44_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l45', 'pack_file': 'l45_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l46', 'pack_file': 'l46_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l47', 'pack_file': 'l47_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l48', 'pack_file': 'l48_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l49', 'pack_file': 'l49_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l50', 'pack_file': 'l50_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l51', 'pack_file': 'l51_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l52', 'pack_file': 'l52_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l53', 'pack_file': 'l53_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l54', 'pack_file': 'l54_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l55', 'pack_file': 'l55_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l56', 'pack_file': 'l56_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l57', 'pack_file': 'l57_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l58', 'pack_file': 'l58_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l59', 'pack_file': 'l59_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l60', 'pack_file': 'l60_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l61', 'pack_file': 'l61_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l62', 'pack_file': 'l62_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l63', 'pack_file': 'l63_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l64', 'pack_file': 'l64_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l65', 'pack_file': 'l65_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l66', 'pack_file': 'l66_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l67', 'pack_file': 'l67_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l68', 'pack_file': 'l68_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l69', 'pack_file': 'l69_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l70', 'pack_file': 'l70_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l71', 'pack_file': 'l71_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l72', 'pack_file': 'l72_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l73', 'pack_file': 'l73_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l74', 'pack_file': 'l74_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l75', 'pack_file': 'l75_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l76', 'pack_file': 'l76_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l77', 'pack_file': 'l77_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l78', 'pack_file': 'l78_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l79', 'pack_file': 'l79_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l80', 'pack_file': 'l80_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l81', 'pack_file': 'l81_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l82', 'pack_file': 'l82_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l83', 'pack_file': 'l83_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l84', 'pack_file': 'l84_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l85', 'pack_file': 'l85_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l86', 'pack_file': 'l86_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l87', 'pack_file': 'l87_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l88', 'pack_file': 'l88_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l89', 'pack_file': 'l89_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l90', 'pack_file': 'l90_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l91', 'pack_file': 'l91_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l92', 'pack_file': 'l92_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l93', 'pack_file': 'l93_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l94', 'pack_file': 'l94_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l95', 'pack_file': 'l95_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l96', 'pack_file': 'l96_core_a1.pack.gz', 'sha256': 'dummysha'},
                {'code': 'l97', 'pack_file': 'l97_core_a1.pack.gz', 'sha256': 'dummysha'},
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

    def add_source(self, source_id, status='APPROVED_FOR_REDISTRIBUTION', dataset_version='1.0.0'):
        source = schema_source(source_id, status=status, dataset_version=dataset_version)
        self.ledger_data['sources'].append(source)
        jsonschema.validate(self.ledger_data, LEDGER_SCHEMA)
        self._write_inputs()
        return source

    def publish(self, code, source_id, *, filename=None, sha256='0' * 64, version='1.0.0', extra=None):
        filename = filename or f'{code}-{version}.pack.gz'
        entry = {
            'id': code,
            'languageCode': code,
            'version': version,
            'path': f'packs/{filename}',
            'sha256': sha256,
            'source_ids': [source_id],
        }
        if extra:
            entry.update(extra)
        self.manifest_data['packs'].append(entry)
        self._write_inputs()
        return entry

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write_bytes(self, filename, payload=b'published-pack'):
        path = os.path.join(self.packs_dir, filename)
        with open(path, 'wb') as handle:
            handle.write(payload)
        return path

    def compile(self):
        output_path = os.path.join(self.test_dir, 'out.json')
        self.compiler.compile(output_path)
        with open(output_path, 'r') as handle:
            return json.load(handle)

    def test_schema_rejects_language_fields_on_sources(self):
        source = schema_source('src-ar')
        source['languages'] = ['ar']
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({'schema_version': '1.0.0', 'sources': [source]}, LEDGER_SCHEMA)
        source.pop('languages')
        source['language'] = 'ar'
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate({'schema_version': '1.0.0', 'sources': [source]}, LEDGER_SCHEMA)

    def test_schema_valid_source_does_not_admit_a_language_by_itself(self):
        self.add_source('src-ar')
        self.assertEqual(admitted_languages(self.ledger_data), set())
        self.assertEqual(admitted_languages(self.ledger_data, self.manifest_data), set())
        res = self.compile()
        self.assertTrue(all(row['status'] in ('metadataOnly', 'licenseBlocked', 'BLOCKED_DEPENDENCY') for row in res['languages'].values()))
        self.assertEqual(res['languages']['ar']['packs'], [])

    def test_language_comes_from_pack_source_provenance(self):
        self.add_source('src-ar')
        self.publish('ar', 'src-ar')
        self.assertEqual(admitted_languages(self.ledger_data, self.manifest_data), {'ar'})
        self.assertNotIn('ru', admitted_languages(self.ledger_data, self.manifest_data))

    def test_forged_language_field_on_a_source_is_ignored(self):
        source = schema_source('src-ar')
        source['languages'] = ['ar']
        self.ledger_data['sources'].append(source)
        self._write_inputs()
        self.assertEqual(admitted_languages(self.ledger_data, self.manifest_data), set())

    def test_review_required_source_does_not_bind_a_pack(self):
        self.add_source('src-ar', status='REVIEW_REQUIRED')
        self.publish('ar', 'src-ar')
        self.assertNotIn('ar', admitted_languages(self.ledger_data, self.manifest_data))
        res = self.compile()
        self.assertEqual(res['languages']['ar']['status'], 'licenseBlocked')
        self.assertEqual(res['languages']['ar']['packs'], [])

    def test_pack_without_matching_source_stays_blocked(self):
        self.publish('ar', 'missing-source')
        self.assertIn('ar', manifest_pack_languages(self.manifest_data))
        self.assertNotIn('ar', admitted_languages(self.ledger_data, self.manifest_data))
        res = self.compile()
        self.assertEqual(res['languages']['ar']['status'], 'licenseBlocked')

    def test_source_ref_dataset_version_must_match(self):
        self.add_source('src-ar', dataset_version='2026-01-01')
        self.publish('ar', 'src-ar', extra={
            'source_ids': None,
            'source_refs': [{
                'source_id': 'src-ar',
                'dataset_version': '1999-01-01',
                'artifact_sha256': DIGEST,
            }],
        })
        self.manifest_data['packs'][-1].pop('source_ids')
        self._write_inputs()
        self.assertNotIn('ar', admitted_languages(self.ledger_data, self.manifest_data))
        self.manifest_data['packs'][-1]['source_refs'][0]['dataset_version'] = '2026-01-01'
        self._write_inputs()
        self.assertIn('ar', admitted_languages(self.ledger_data, self.manifest_data))

    def test_all_registered_ids_processed(self):
        res = self.compile()
        self.assertEqual(res['total_languages'], 100)
        self.assertEqual(len(res['languages']), 100)
        self.assertTrue(all(row['status'] in ('metadataOnly', 'licenseBlocked', 'BLOCKED_DEPENDENCY') for row in res['languages'].values()))

    def test_missing_published_file_is_source_missing(self):
        self.add_source('src-ar')
        self.publish('ar', 'src-ar', filename='ar-1.0.0.pack.gz')
        res = self.compile()
        self.assertEqual(res['languages']['ar']['status'], 'sourceMissing')
        self.assertFalse(res['languages']['ar']['packs'][0]['valid'])

    def test_legacy_glob_does_not_satisfy_a_published_pack(self):
        self.add_source('src-ar')
        self.publish('ar', 'src-ar', filename='ar-1.0.0.pack.gz', sha256='f' * 64)
        legacy = self.write_bytes('ar_core_a1.pack.gz', b'legacy-bytes')
        legacy_hash = hashlib.sha256(b'legacy-bytes').hexdigest()
        self.manifest_data['languages'][0]['sha256'] = legacy_hash
        self.manifest_data['languages'][0]['pack_file'] = 'ar_core_a1.pack.gz'
        self._write_inputs()
        self.assertTrue(os.path.isfile(legacy))
        res = self.compile()
        row = res['languages']['ar']
        self.assertEqual(row['status'], 'sourceMissing')
        self.assertNotEqual(row['status'], 'releaseReady')
        self.assertTrue(all(not pack.get('valid') for pack in row['packs']))
        self.assertNotIn('ar_core_a1.pack.gz', [pack.get('file') for pack in row['packs']])

    def test_sha256_mismatch_on_the_published_path_is_invalid(self):
        self.add_source('src-ru')
        path = self.write_bytes('ru-1.0.0.pack.gz', b'real-bytes')
        actual = self.compiler.compute_sha256(path)
        self.publish('ru', 'src-ru', filename='ru-1.0.0.pack.gz', sha256='0' * 64)
        self.write_bytes('ru_core_a1.pack.gz', b'legacy')
        res = self.compile()
        row = res['languages']['ru']
        self.assertEqual(row['status'], 'invalidPack')
        self.assertTrue(any('sha256' in reason for reason in row['reasons']))
        self.assertNotEqual(row['packs'][0]['actual_sha256'], '0' * 64)
        self.assertEqual(row['packs'][0]['actual_sha256'], actual)
        self.assertFalse(row['packs'][0]['valid'])

    def test_release_ready_only_when_published_path_and_hash_match(self):
        self.add_source('src-ar')
        path = self.write_bytes('ar-1.0.0.pack.gz', b'arabic-published')
        actual = self.compiler.compute_sha256(path)
        self.publish('ar', 'src-ar', filename='ar-1.0.0.pack.gz', sha256=actual)
        self.write_bytes('ar_universal_v1.pack.gz', b'unrelated-legacy')
        res = self.compile()
        row = res['languages']['ar']
        self.assertEqual(row['status'], 'releaseReady')
        self.assertTrue(row['packs'][0]['valid'])
        self.assertEqual(row['packs'][0]['file'], 'packs/ar-1.0.0.pack.gz')
        self.assertEqual(row['packs'][0]['actual_sha256'], actual)
        self.assertEqual(res['languages']['ru']['status'], 'metadataOnly')

    def test_path_escape_is_not_release_ready(self):
        self.add_source('src-ar')
        outside = os.path.join(self.test_dir, 'escaped.pack.gz')
        with open(outside, 'wb') as handle:
            handle.write(b'escaped')
        digest = hashlib.sha256(b'escaped').hexdigest()
        self.publish('ar', 'src-ar', extra={'path': '../escaped.pack.gz', 'sha256': digest})
        res = self.compile()
        self.assertNotEqual(res['languages']['ar']['status'], 'releaseReady')
        self.assertFalse(res['languages']['ar']['packs'][0]['valid'])

    def test_fail_closed_no_overwrite(self):
        output_path = os.path.join(self.test_dir, 'out.json')
        with open(output_path, 'w') as handle:
            json.dump({'original': True}, handle)
        self.compiler.load_manifest_document = lambda: (_ for _ in ()).throw(Exception('Force fail'))
        with self.assertRaises(Exception):
            self.compiler.compile(output_path)
        with open(output_path, 'r') as handle:
            self.assertTrue(json.load(handle).get('original'))
        self.assertFalse(os.path.exists(output_path + '.tmp'))

    def test_committed_evidence_requires_bound_pack(self):
        evidence = json.loads((ROOT / 'tools/final_release_evidence/release_evidence.json').read_text())
        ledger = json.loads((ROOT / 'legal/ledger/sources.json').read_text())
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        jsonschema.validate(ledger, LEDGER_SCHEMA)
        admitted = admitted_languages(ledger, manifest)
        published = manifest_pack_languages(manifest)
        languages = evidence['languages']
        self.assertEqual(evidence['total_languages'], len(languages))
        for code, row in languages.items():
            packs = row.get('packs') or []
            if row.get('status') == 'releaseReady' or any(pack.get('valid') for pack in packs):
                self.assertIn(code, admitted, f'{code} is release-ready without a bound approved source')
                self.assertIn(code, published, f'{code} is release-ready without a manifest pack')
        if not ledger.get('sources') and not manifest.get('packs'):
            self.assertEqual(admitted, set())
            self.assertTrue(all(row.get('status') == 'BLOCKED_DEPENDENCY' for row in languages.values()))
            self.assertTrue(all(row.get('packs') == [] for row in languages.values()))


if __name__ == '__main__':
    unittest.main()
