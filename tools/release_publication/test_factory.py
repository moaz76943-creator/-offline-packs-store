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

    def test_invalid_vct_rejected(self):
        vct_file = self.root / "bad.vct"
        vct_file.write_bytes(b"not a valid vct token")
        artifacts = [{"path": "bad.vct", "sha256": file_hash(vct_file)}]
        with self.assertRaisesRegex(ValueError, "Invalid compact semantic asset"):
            publish_artifacts(self.root, self.target, artifacts, check_auth=False)

    def test_unapproved_language_rejected_with_auth(self):
        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "unsupported_lang"}]
        # mock registry
        cat_dir = self.root / "catalog"
        cat_dir.mkdir(parents=True, exist_ok=True)
        (cat_dir / "language_registry.v1.json").write_text('{"languages": [{"code": "de"}, {"code": "en"}]}')

        # we need to skip other auth checks for this test to fail specifically on language
        # or we mock check_auth, but check_auth=True runs the release gate which will fail
        # let's just make it check_auth=True and mock verify_publication_eligibility and verify_publication_authorization

        import tools.release_publication.factory as f
        old_eligibility = f.verify_publication_eligibility
        old_auth = f.verify_publication_authorization
        old_validate = f.validate_artifact
        f.verify_publication_eligibility = lambda r: {"status": "VERIFIED_CANDIDATE"}
        f.verify_publication_authorization = lambda r: None
        f.validate_artifact = lambda a, r: []

        try:
            with self.assertRaisesRegex(ValueError, "Unapproved language: unsupported_lang"):
                publish_artifacts(self.root, self.target, artifacts, check_auth=True)
        finally:
            f.verify_publication_eligibility = old_eligibility
            f.verify_publication_authorization = old_auth
            f.validate_artifact = old_validate


    def test_gate_validation_failure(self):
        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]

        import tools.release_publication.factory as f
        old_eligibility = f.verify_publication_eligibility
        old_auth = f.verify_publication_authorization
        old_validate = f.validate_artifact
        f.verify_publication_eligibility = lambda r: {"status": "VERIFIED_CANDIDATE"}
        f.verify_publication_authorization = lambda r: None
        f.validate_artifact = lambda a, r: ["INVALID_LICENSE"]

        try:
            with self.assertRaisesRegex(ValueError, "failed validation: \\['INVALID_LICENSE'\\]"):
                publish_artifacts(self.root, self.target, artifacts, check_auth=True)
        finally:
            f.verify_publication_eligibility = old_eligibility
            f.verify_publication_authorization = old_auth
            f.validate_artifact = old_validate
