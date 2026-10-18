import json
import tempfile
import unittest
from pathlib import Path
from tools.release_publication.factory import publish_artifacts, file_hash

class TestPublicationFactory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.valid_artifact = self.root / "deutsch_deep_master.pack.gz"
        # copy real fixture
        import shutil
        repo_root = Path(__file__).resolve().parents[2]
        shutil.copy2(repo_root / "deutsch_deep_master.pack.gz", self.valid_artifact)

        self.valid_hash = file_hash(self.valid_artifact)
        self.target = self.root / "published"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_publish_valid_artifacts(self):
        # Even with check_auth=False, it validates the file size and formats
        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]
        publish_artifacts(self.root, self.target, artifacts, check_auth=False)

        self.assertTrue((self.target / "deutsch_deep_master.pack.gz").exists())
        self.assertTrue((self.target / "deutsch_deep_master.pack.gz.manifest.json").exists())

    def test_invalid_hash_fails(self):
        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": "invalid"}]
        with self.assertRaises(ValueError):
            publish_artifacts(self.root, self.target, artifacts, check_auth=False)

    def test_dry_run_prevents_writes(self):
        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]
        publish_artifacts(self.root, self.target, artifacts, dry_run=True, check_auth=False)

        self.assertFalse(self.target.exists())

    def test_atomic_rollback(self):
        self.target.mkdir()
        (self.target / "old_pack").write_bytes(b"old")

        self.invalid_artifact = self.root / "invalid.pack.gz"
        self.invalid_artifact.write_bytes(b"bad")

        artifacts = [{"path": "invalid.pack.gz", "sha256": "wrong_hash"}]
        with self.assertRaises(ValueError):
            publish_artifacts(self.root, self.target, artifacts, check_auth=False)

        self.assertTrue(self.target.exists())
        self.assertTrue((self.target / "old_pack").exists())

    def test_size_limit(self):
        import tools.release_publication.factory
        old_limit = tools.release_publication.factory.MAX_FILE_SIZE
        tools.release_publication.factory.MAX_FILE_SIZE = 2
        try:
            artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]
            with self.assertRaises(ValueError):
                publish_artifacts(self.root, self.target, artifacts, check_auth=False)
        finally:
            tools.release_publication.factory.MAX_FILE_SIZE = old_limit

    def test_path_traversal_blocked(self):
        artifacts = [{"path": "../outside.pack.gz", "sha256": "anything"}]
        with self.assertRaisesRegex(ValueError, "Path traversal detected"):
            publish_artifacts(self.root, self.target, artifacts, check_auth=False)

    def test_unsupported_format(self):
        bad_format = self.root / "bad.txt"
        bad_format.write_bytes(b"abc")
        artifacts = [{"path": "bad.txt", "sha256": file_hash(bad_format)}]
        with self.assertRaisesRegex(ValueError, "Unsupported format"):
            publish_artifacts(self.root, self.target, artifacts, check_auth=False)

    def test_auth_check_fails_without_creds(self):
        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]
        with self.assertRaises(ValueError):
            publish_artifacts(self.root, self.target, artifacts, check_auth=True)
