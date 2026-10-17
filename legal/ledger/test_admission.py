import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from admission import evaluate, sha256_file


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.put('evidence/upstream.json', b'{"word":"hello"}')
        self.lic = self.put('evidence/upstream-license.txt', b'Fixture publisher CC0-1.0 license assertion')
        self.pack = self.put('packs/fixture.json', b'{"entries":1}')
        self.notice = self.put('notices/attribution.txt', b'fixture-source Fixture Publisher CC0-1.0 https://example.org/data')
        self.source = {
            'source_id': 'fixture-source', 'kind': 'dictionary',
            'origin_url': 'https://example.org/data', 'publisher': 'Fixture Publisher',
            'dataset_version': '2026.10',
            'retrieval': {'identity': 'fixture-snapshot-v1', 'url': 'https://example.org/data',
                          'date': '2026-10-12', 'artifact_path': 'evidence/upstream.json',
                          'sha256': sha256_file(self.root / self.src)},
            'license': {'id': 'CC0-1.0', 'evidence_url': 'https://example.org/data/license',
                        'evidence_path': 'evidence/upstream-license.txt',
                        'evidence_sha256': sha256_file(self.root / self.lic)},
            'status': 'APPROVED_FOR_REDISTRIBUTION',
            'review': {'reviewer': 'fixture-reviewer', 'decision_url': 'https://example.org/review/1'},
            'alterations': ['no changes'],
        }
        self.candidate = {
            'asset_id': 'fixture-dictionary', 'kind': 'dictionary',
            'artifact_path': 'packs/fixture.json', 'sha256': sha256_file(self.root / self.pack),
            'source_refs': [{'source_id': 'fixture-source', 'dataset_version': '2026.10',
                             'artifact_sha256': self.source['retrieval']['sha256']}],
            'output_license_id': 'CC0-1.0', 'compiler_license_id': 'MIT',
            'notices': {'fixture-source': 'notices/attribution.txt'},
            'compliance': {}, 'provenance_mode': 'per_record',
            'record_sources': [{'record_id': 'entry-1', 'source_ids': ['fixture-source']}],
            'review': {'reviewer': 'fixture-reviewer', 'decision_url': 'https://example.org/review/2'},
        }
        self.ledger = {'schema_version': '1.0.0', 'sources': [self.source]}
        self.daily = [{'schema_version': '1.0.0', 'date': '2026-10-12', 'release_candidates': [self.candidate]}]
        self.manifest = {'languages': [], 'packs': []}

    def put(self, path, content):
        out = self.root / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        return path

    def issues(self):
        return evaluate(self.ledger, self.manifest, self.daily, self.root)

    def test_valid_evidence_does_not_auto_approve_but_accepts_documented_review(self):
        self.assertEqual([], self.issues())

    def test_unknown_rights_are_blocked(self):
        self.source['license']['id'] = 'PUBLIC_DOMAIN_ZERO_COPYRIGHT'
        self.assertIn('BLOCKED_LICENSE', str(self.issues()))

    def test_review_required_is_not_approved(self):
        self.source['status'] = 'REVIEW_REQUIRED'
        self.assertIn('REVIEW_REQUIRED', str(self.issues()))

    def test_mismatched_source_version(self):
        self.candidate['source_refs'][0]['dataset_version'] = '2025.01'
        self.assertIn('VERSION_MISMATCH', str(self.issues()))

    def test_missing_license_evidence(self):
        self.source['license']['evidence_path'] = 'evidence/missing.txt'
        self.assertIn('EVIDENCE', str(self.issues()))

    def test_wrong_original_artifact_hash(self):
        self.source['retrieval']['sha256'] = '0' * 64
        self.assertIn('HASH_MISMATCH', str(self.issues()))

    def test_missing_redistribution_notice(self):
        self.candidate['notices'] = {}
        self.assertIn('NOTICE', str(self.issues()))

    def test_manifest_blanket_public_domain_is_blocked(self):
        self.manifest['intellectual_property_status'] = 'PUBLIC_DOMAIN_ZERO_COPYRIGHT'
        self.assertIn('BLOCKED_LICENSE', str(self.issues()))

    def test_active_legacy_pack_without_candidate_is_blocked(self):
        self.manifest['languages'] = [{'code': 'de', 'is_active': True, 'pack_file': 'de_universal_v1.pack.gz'}]
        self.assertIn('UNVERIFIED_RELEASE', str(self.issues()))

    def test_cannot_launder_sharealike_as_cc0(self):
        self.source['license']['id'] = 'CC-BY-SA-4.0'
        self.candidate['output_license_id'] = 'CC0-1.0'
        self.assertIn('LICENSE_CONFLICT', str(self.issues()))

    def test_gfdl_is_not_automatically_by_sa(self):
        self.source['license']['id'] = 'GFDL-1.3-only'
        self.candidate['output_license_id'] = 'CC-BY-SA-4.0'
        self.assertIn('LICENSE_CONFLICT', str(self.issues()))

    def test_by_sa_requirements_are_individual(self):
        self.source['license']['id'] = 'CC-BY-SA-4.0'
        self.candidate['output_license_id'] = 'CC-BY-SA-4.0'
        self.assertIn('OBLIGATION', str(self.issues()))

    def test_gfdl_requirements_are_individual(self):
        self.source['license']['id'] = 'GFDL-1.3-only'
        self.candidate['output_license_id'] = 'GFDL-1.3-only'
        self.assertIn('OBLIGATION', str(self.issues()))

    def test_public_domain_requires_jurisdiction_basis_and_proof(self):
        self.source['license']['id'] = 'PUBLIC-DOMAIN'
        self.candidate['output_license_id'] = 'PUBLIC-DOMAIN'
        self.assertIn('PD_PROOF', str(self.issues()))

    def test_vector_art_needs_separate_artwork_evidence(self):
        self.source['kind'] = 'vector_art'
        self.candidate['kind'] = 'vector_art'
        self.candidate['provenance_mode'] = 'source_set'
        self.candidate['record_sources'] = []
        self.candidate['record_provenance_reason'] = 'not lexical'
        self.assertIn('ARTWORK_LICENSE', str(self.issues()))

    def test_daily_unsupported_schema_rejected(self):
        self.daily[0]['schema_version'] = '2.0.0'
        self.assertIn('SCHEMA_VERSION', str(self.issues()))

    def test_missing_record_provenance_rejected(self):
        self.candidate['record_sources'] = []
        self.assertIn('RECORD_PROVENANCE', str(self.issues()))

    def test_unapproved_candidate_rejected(self):
        del self.candidate['review']
        self.assertIn('MANUAL_REVIEW', str(self.issues()))

    def test_path_escape_rejected(self):
        self.source['retrieval']['artifact_path'] = '../secret.json'
        self.assertIn('EVIDENCE', str(self.issues()))

    def test_duplicate_source_id_rejected(self):
        self.ledger['sources'].append(copy.deepcopy(self.source))
        self.assertIn('DUPLICATE', str(self.issues()))


    def test_internal_symlink_license_proof_rejected_even_with_matching_sha(self):
        (self.root / 'evidence/license-link.txt').symlink_to('upstream-license.txt')
        self.source['license']['evidence_path'] = 'evidence/license-link.txt'
        self.assertIn('EVIDENCE', str(self.issues()))

    def test_cc0_metadata_conflicts_with_noncommercial_license_notice(self):
        self.put('evidence/upstream-license.txt', b'Official license: CC BY-NC-SA 4.0\n')
        self.source['license']['evidence_sha256'] = sha256_file(
            self.root / 'evidence/upstream-license.txt')
        self.assertIn('LICENSE_CONFLICT', str(self.issues()))

    def test_cc_by_sa_and_gfdl_needs_an_explicit_co_offer(self):
        notice = b'made available under CC-BY-SA and GFDL\n'
        self.put('evidence/upstream-license.txt', notice)
        self.source['license']['id'] = 'CC-BY-SA-4.0'
        self.source['license']['evidence_sha256'] = sha256_file(
            self.root / 'evidence/upstream-license.txt')
        self.assertIn('license notice conflicts', str(self.issues()))
        self.source['license']['co_offered_licenses'] = ['GFDL-1.3-only']
        self.assertNotIn('license notice conflicts', str(self.issues()))
        self.put('evidence/upstream-license.txt', b'CC-BY-SA and GFDL and CC BY-NC 4.0\n')
        self.source['license']['evidence_sha256'] = sha256_file(
            self.root / 'evidence/upstream-license.txt')
        self.assertIn('license notice conflicts', str(self.issues()))


if __name__ == '__main__':
    unittest.main()
