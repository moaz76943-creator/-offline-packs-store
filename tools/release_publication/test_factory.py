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

        # Mock the tools used by check_auth=False or write_attribution
        self.compiler_script = self.root / "tools/provenance_release/compiler.py"
        self.compiler_script.parent.mkdir(parents=True, exist_ok=True)
        self.compiler_script.write_text("""
import sys, argparse
parser = argparse.ArgumentParser()
parser.add_argument('--repo-root')
parser.add_argument('--daily-dir')
parser.add_argument('--manifest-out')
parser.add_argument('--notice-out')
args = parser.parse_args()
with open(args.manifest_out, 'w') as f:
    f.write('{"schema_version": "1.0.0"}')
with open(args.notice_out, 'w') as f:
    f.write('NOTICE')
""")

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

    def test_auth_pack_conformance_failure(self):
        # Create mock creds to bypass auth error, so we fail on pack conformance
        creds = self.root / ".credentials/publisher"
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text("dummy")

        # Give valid hash but an invalid pack (not a real db)
        invalid_pack = self.root / "invalid.pack.gz"
        import gzip
        with gzip.open(invalid_pack, 'wb') as f:
            f.write(b"not a database")

        # also mock validator script to just pass
        validator_script = self.root / "tools/release_validation/validator.py"
        validator_script.parent.mkdir(parents=True, exist_ok=True)
        validator_script.write_text("""
import sys, json, argparse
parser = argparse.ArgumentParser()
parser.add_argument('--repo-root')
parser.add_argument('--candidates')
parser.add_argument('--output')
args = parser.parse_args()
with open(args.candidates) as f:
    c = json.load(f)
with open(args.output, 'w') as f:
    json.dump({"approved_artifacts": c["artifacts"]}, f)
""")
        # Create fake conformance check that will fail
        conformance_script = self.root / "tools/pack_conformance/validator.py"
        conformance_script.parent.mkdir(parents=True, exist_ok=True)
        conformance_script.write_text("""
import sys
sys.stderr.write("conformance check failed\\n")
sys.exit(1)
""")

        artifacts = [{"path": "invalid.pack.gz", "sha256": file_hash(invalid_pack), "language": "de"}]
        with self.assertRaisesRegex(ValueError, "Pack conformance check failed"):
            publish_artifacts(self.root, self.target, artifacts, check_auth=True)

    def test_auth_publication_eligibility_failure(self):
        creds = self.root / ".credentials/publisher"
        creds.parent.mkdir(parents=True, exist_ok=True)
        creds.write_text("dummy")

        # mock validator script to fail
        validator_script = self.root / "tools/release_validation/validator.py"
        validator_script.parent.mkdir(parents=True, exist_ok=True)
        validator_script.write_text("""
import sys
sys.stdout.write("blocked publication\\n")
sys.exit(1)
""")

        artifacts = [{"path": "deutsch_deep_master.pack.gz", "sha256": self.valid_hash, "language": "de"}]
        with self.assertRaisesRegex(ValueError, "Release gate blocked publication"):
            publish_artifacts(self.root, self.target, artifacts, check_auth=True)
