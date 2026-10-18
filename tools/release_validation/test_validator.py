import unittest
import os
import json
import tempfile
import hashlib
from pathlib import Path

from tools.release_validation.validator import validate_artifact, evaluate_candidates

class TestReleaseEligibilityGate(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)

        self.valid_file = self.repo_root / "test.pack.gz"
        self.valid_content = b"fake pack content"
        self.valid_file.write_bytes(self.valid_content)
        self.valid_hash = hashlib.sha256(self.valid_content).hexdigest()

        self.valid_artifact = {
            "id": "test_pack",
            "path": "test.pack.gz",
            "sha256": self.valid_hash,
            "license": "CC0-1.0",
            "repository_authorization": "VERIFIED_FOR_AUTHORIZED_HANDOFF",
            "validations": {
                "schema_conformance": "PASSED",
                "format_conformance": "PASSED",
                "provenance_evidence": "PASSED",
                "attribution_evidence": "PASSED"
            }
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_artifact_passes(self):
        reasons = validate_artifact(self.valid_artifact, self.repo_root)
        self.assertEqual(reasons, [])

    def test_missing_identity(self):
        artifact = self.valid_artifact.copy()
        del artifact['id']
        reasons = validate_artifact(artifact, self.repo_root)
        self.assertIn("MISSING_IDENTITY", reasons)

    def test_missing_path(self):
        artifact = self.valid_artifact.copy()
        del artifact['path']
        reasons = validate_artifact(artifact, self.repo_root)
        self.assertIn("MISSING_PATH", reasons)

    def test_file_not_found(self):
        artifact = self.valid_artifact.copy()
        artifact['path'] = "nonexistent.pack.gz"
        reasons = validate_artifact(artifact, self.repo_root)
        self.assertIn("FILE_NOT_FOUND", reasons)

    def test_hash_mismatch(self):
        artifact = self.valid_artifact.copy()
        artifact['sha256'] = "0000000000000000000000000000000000000000000000000000000000000000"
        reasons = validate_artifact(artifact, self.repo_root)
        self.assertIn("HASH_MISMATCH", reasons)

    def test_missing_license(self):
        artifact = self.valid_artifact.copy()
        del artifact['license']
        reasons = validate_artifact(artifact, self.repo_root)
        self.assertIn("MISSING_LICENSE", reasons)

    def test_invalid_license(self):
        artifact = self.valid_artifact.copy()
        artifact['license'] = "GPL-3.0"
        reasons = validate_artifact(artifact, self.repo_root)
        self.assertIn("UNAPPROVED_LICENSE", reasons)

    def test_missing_validation_not_run(self):
        artifact = self.valid_artifact.copy()
        del artifact['validations']['schema_conformance']
        reasons = validate_artifact(artifact, self.repo_root)
        self.assertIn("SCHEMA_CONFORMANCE_NOT_RUN", reasons)

    def test_failed_validation(self):
        artifact = self.valid_artifact.copy()
        artifact['validations']['format_conformance'] = "FAILED"
        reasons = validate_artifact(artifact, self.repo_root)
        self.assertIn("FORMAT_CONFORMANCE_FAILED", reasons)

    def test_evaluate_candidates_all_pass(self):
        candidates_path = self.repo_root / "candidates.json"
        candidates_path.write_text(json.dumps({
            "artifacts": [self.valid_artifact]
        }))

        output_path = self.repo_root / "approved.json"

        exit_code, report = evaluate_candidates(candidates_path, self.repo_root, output_path)

        self.assertEqual(exit_code, 0)
        self.assertTrue(output_path.exists())
        self.assertEqual(report[self.valid_artifact['id']], ["PASSED"])

        with open(output_path, 'r') as f:
            manifest = json.load(f)

        self.assertEqual(manifest['schema_version'], "1.0.0")
        self.assertEqual(len(manifest['approved_artifacts']), 1)
        self.assertEqual(manifest['approved_artifacts'][0]['id'], self.valid_artifact['id'])

    def test_evaluate_candidates_one_fails(self):
        invalid_artifact = self.valid_artifact.copy()
        invalid_artifact['id'] = 'invalid_pack'
        invalid_artifact['sha256'] = 'wrong'

        candidates_path = self.repo_root / "candidates.json"
        candidates_path.write_text(json.dumps({
            "artifacts": [self.valid_artifact, invalid_artifact]
        }))

        output_path = self.repo_root / "approved.json"

        exit_code, report = evaluate_candidates(candidates_path, self.repo_root, output_path)

        self.assertEqual(exit_code, 1)
        self.assertFalse(output_path.exists())
        self.assertEqual(report[self.valid_artifact['id']], ["PASSED"])
        self.assertIn("HASH_MISMATCH", report['invalid_pack'])

    def test_missing_authorization(self):
        artifact = self.valid_artifact.copy()
        del artifact['repository_authorization']
        reasons = validate_artifact(artifact, self.repo_root)
        self.assertIn('UNAUTHORIZED_REPOSITORY', reasons)

    def test_invalid_authorization(self):
        artifact = self.valid_artifact.copy()
        artifact['repository_authorization'] = 'UNKNOWN'
        reasons = validate_artifact(artifact, self.repo_root)
        self.assertIn('UNAUTHORIZED_REPOSITORY', reasons)

if __name__ == '__main__':
    unittest.main()
