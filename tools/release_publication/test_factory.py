import json
import tempfile
import unittest
import os
from pathlib import Path
from tools.release_publication.factory import publish_artifacts, file_hash

class TestPublicationFactory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.valid_artifact = self.root / "deutsch_deep_master.pack.gz"
        # copy real fixture
        import shutil
        self.repo_root = Path(__file__).resolve().parents[2]
        shutil.copy2(self.repo_root / "deutsch_deep_master.pack.gz", self.valid_artifact)

        self.valid_hash = file_hash(self.valid_artifact)
        self.target = self.root / "published"

        self.artifacts_json_path = self.root / "artifacts.json"

        # We need provenance compiler available, create a mock daily dir/ledger if we don't have it
        self.ledger_dir = self.root / "legal" / "ledger"
        self.ledger_dir.mkdir(parents=True)
        self.daily_dir = self.ledger_dir / "daily"
        self.daily_dir.mkdir()

        with open(self.ledger_dir / "sources.json", "w") as f:
            json.dump({"sources": []}, f)

    def _write_artifacts(self, artifacts_list):
        with open(self.artifacts_json_path, 'w') as f:
            json.dump({"artifacts": artifacts_list}, f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_publish_valid_artifacts(self):
        # Create a mock provenance compiler wrapper to avoid actual provenance generation logic failing on empty data
        artifacts = [{
            "id": "pack1",
            "path": "deutsch_deep_master.pack.gz",
            "sha256": self.valid_hash,
            "language": "de",
            "license": "CC0-1.0",
            "repository_authorization": "VERIFIED_FOR_AUTHORIZED_HANDOFF",
            "validations": {
                "schema_conformance": "PASSED",
                "format_conformance": "PASSED",
                "provenance_evidence": "PASSED",
                "attribution_evidence": "PASSED"
            }
        }]
        self._write_artifacts(artifacts)

        # Mock generate_provenance
        import tools.release_publication.factory
        original_generate = tools.release_publication.factory.generate_provenance

        def mock_generate(repo_root, manifest_out, notice_out):
            with open(manifest_out, 'w') as f:
                json.dump({"schema_version": "1.0.0"}, f)
            with open(notice_out, 'w') as f:
                f.write("ATTRIBUTION NOTICES\n")

        tools.release_publication.factory.generate_provenance = mock_generate
        try:
            publish_artifacts(self.root, self.target, self.artifacts_json_path, check_auth=False)
        finally:
            tools.release_publication.factory.generate_provenance = original_generate

        self.assertTrue((self.target / "deutsch_deep_master.pack.gz").exists())
        self.assertTrue((self.target / "release_provenance.json").exists())
        self.assertTrue((self.target / "NOTICE.txt").exists())

    def test_invalid_hash_fails(self):
        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": "invalid"}]
        self._write_artifacts(artifacts)
        with self.assertRaises(ValueError):
            publish_artifacts(self.root, self.target, self.artifacts_json_path, check_auth=False)

    def test_dry_run_prevents_writes(self):
        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]
        self._write_artifacts(artifacts)
        publish_artifacts(self.root, self.target, self.artifacts_json_path, dry_run=True, check_auth=False)

        self.assertFalse(self.target.exists())

    def test_atomic_rollback(self):
        self.target.mkdir()
        (self.target / "old_pack").write_bytes(b"old")

        self.invalid_artifact = self.root / "invalid.pack.gz"
        self.invalid_artifact.write_bytes(b"bad")

        artifacts = [{"path": "invalid.pack.gz", "sha256": "wrong_hash"}]
        self._write_artifacts(artifacts)
        with self.assertRaises(ValueError):
            publish_artifacts(self.root, self.target, self.artifacts_json_path, check_auth=False)

        self.assertTrue(self.target.exists())
        self.assertTrue((self.target / "old_pack").exists())

    def test_size_limit(self):
        import tools.release_publication.factory
        old_limit = tools.release_publication.factory.MAX_FILE_SIZE
        tools.release_publication.factory.MAX_FILE_SIZE = 2

        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]
        self._write_artifacts(artifacts)

        try:
            with self.assertRaises(ValueError):
                publish_artifacts(self.root, self.target, self.artifacts_json_path, check_auth=False)
        finally:
            tools.release_publication.factory.MAX_FILE_SIZE = old_limit

    def test_outside_target_rejected_without_is_relative_to(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(outside, ignore_errors=True))

        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]
        self._write_artifacts(artifacts)

        with self.assertRaisesRegex(ValueError, "within repository"):
            publish_artifacts(self.root, outside, self.artifacts_json_path, check_auth=False)
        self.assertFalse((outside / "deutsch_deep_master.pack.gz").exists())

    def test_path_traversal_blocked(self):
        artifacts = [{"path": "../outside.pack.gz", "sha256": "anything"}]
        self._write_artifacts(artifacts)
        with self.assertRaisesRegex(ValueError, "Path traversal detected"):
            publish_artifacts(self.root, self.target, self.artifacts_json_path, check_auth=False)

    def test_unsupported_format(self):
        bad_format = self.root / "bad.txt"
        bad_format.write_bytes(b"abc")

        artifacts = [{"path": "bad.txt", "sha256": file_hash(bad_format)}]
        self._write_artifacts(artifacts)

        with self.assertRaisesRegex(ValueError, "Unsupported format"):
            publish_artifacts(self.root, self.target, self.artifacts_json_path, check_auth=False)

    def test_auth_check_fails_without_creds(self):
        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]
        self._write_artifacts(artifacts)
        with self.assertRaises(ValueError):
            publish_artifacts(self.root, self.target, self.artifacts_json_path, check_auth=True)
