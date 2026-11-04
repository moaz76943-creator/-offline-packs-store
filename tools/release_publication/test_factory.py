import json
import tempfile
import unittest
import sys
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

        self.valid_vct = self.root / "test.vct"
        # make a dummy vct and copy from core.encode_token if we can
        try:
             repo_str = str(self.repo_root)
             if repo_str not in sys.path:
                 sys.path.insert(0, repo_str)
             from tools.visual_lexicon.core import encode_token
             token_data = {
                 "concept_id": "test_id",
                 "version": 1,
                 "viewBox": [0, 0, 100, 100],
                 "paths": ["M10 10 H 90 V 90 H 10 Z"],
                 "palette": ["#000000"],
                 "semantic_label": "test",
                 "license": "CC0-1.0",
                 "source_hash": "test",
                 "author": "test"
             }
             compressed, _ = encode_token(token_data)
             self.valid_vct.write_bytes(compressed)
             self.valid_vct_hash = file_hash(self.valid_vct)
        except Exception as e:
             print("Error generating vct:", e)

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

    def test_outside_target_rejected_without_is_relative_to(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(outside, ignore_errors=True))
        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]
        with self.assertRaisesRegex(ValueError, "within repository"):
            publish_artifacts(self.root, outside, artifacts, check_auth=False)
        self.assertFalse((outside / "deutsch_deep_master.pack.gz").exists())

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

    def test_vct_validation(self):
        if self.valid_vct.exists():
            artifacts = [{"path": "test.vct", "sha256": self.valid_vct_hash}]
            publish_artifacts(self.root, self.target, artifacts, check_auth=False)
            self.assertTrue((self.target / "test.vct").exists())

            invalid_vct = self.root / "invalid.vct"
            invalid_vct.write_bytes(b"invalid data")
            invalid_hash = file_hash(invalid_vct)
            artifacts = [{"path": "invalid.vct", "sha256": invalid_hash}]
            with self.assertRaises(ValueError):
                publish_artifacts(self.root, self.target, artifacts, check_auth=False)
        else:
            self.fail("valid_vct does not exist")
