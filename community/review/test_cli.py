import base64
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from community.review.cli import main
from community.review.state_machine import ReviewStateMachine, canonical


class TestReviewCLI(unittest.TestCase):

    def setUp(self):
        self.storage = tempfile.mkdtemp(prefix="test_storage_")
        self.artifacts = tempfile.mkdtemp(prefix="test_artifacts_")
        self.keys_dir = tempfile.mkdtemp(prefix="test_keys_")

        self.validator_key = os.urandom(32)
        self.reviewer_key = os.urandom(32)

        self.operator_keys_file = Path(self.keys_dir) / "keys.json"
        self.operator_keys_file.write_text(json.dumps({
            "validators": {"validator1": base64.b64encode(self.validator_key).decode("utf-8")},
            "reviewers": {"reviewer1": base64.b64encode(self.reviewer_key).decode("utf-8")}
        }))
        self.operator_keys_file.chmod(0o600)

        self.sid = "test-sub-123"
        self.content = b"test content"
        self.content_hash = hashlib.sha256(self.content).hexdigest()

        self.artifact_path = Path(self.artifacts) / "test_artifact.pack"
        with open(self.artifact_path, "wb") as f:
            f.write(self.content)

        self.metadata = {
            "source_id": "src_1",
            "language": "en",
            "sense_id": "sense_1",
            "license_id": "CC0-1.0",
            "dataset_version": "1.0",
            "publisher": "Test Pub",
            "origin_url": "http://example.com",
            "record_locator": "loc_1",
            "source_artifact_sha256": "0" * 64,
            "rights_status": "APPROVED_FOR_REDISTRIBUTION",
            "fixture_only": False,
        }
        self.metadata_path = Path(self.artifacts) / "metadata.json"
        self.metadata_path.write_text(json.dumps(self.metadata))

    def tearDown(self):
        shutil.rmtree(self.storage)
        shutil.rmtree(self.artifacts)
        shutil.rmtree(self.keys_dir)

    def test_submit(self):
        argv = [
            "--storage", self.storage,
            "--artifacts", self.artifacts,
            "--operator-keys", str(self.operator_keys_file),
            "submit",
            "--id", self.sid,
            "--sha256", self.content_hash,
            "--metadata", str(self.metadata_path),
            "--artifact", str(self.artifact_path)
        ]
        self.assertEqual(main(argv), 0)

    def test_missing_args_submit(self):
        argv = [
            "--storage", self.storage,
            "--artifacts", self.artifacts,
            "--operator-keys", str(self.operator_keys_file),
            "submit",
            "--id", self.sid
        ]
        self.assertEqual(main(argv), 1)

    def test_full_flow(self):
        argv = [
            "--storage", self.storage,
            "--artifacts", self.artifacts,
            "--operator-keys", str(self.operator_keys_file),
            "submit",
            "--id", self.sid,
            "--sha256", self.content_hash,
            "--metadata", str(self.metadata_path),
            "--artifact", str(self.artifact_path)
        ]
        self.assertEqual(main(argv), 0)

        argv = [
            "--storage", self.storage,
            "--artifacts", self.artifacts,
            "--operator-keys", str(self.operator_keys_file),
            "start",
            "--id", self.sid
        ]
        self.assertEqual(main(argv), 0)

        # Get token
        machine = ReviewStateMachine(self.storage, self.artifacts,
                                     validator_keys={"validator1": self.validator_key},
                                     reviewer_keys={"reviewer1": self.reviewer_key})
        state = machine._read(self.sid)
        payload = ReviewStateMachine.payload(state, "VALIDATE", "validator1")
        import hmac
        token = hmac.new(self.validator_key, canonical(payload), hashlib.sha256).hexdigest()

        argv = [
            "--storage", self.storage,
            "--artifacts", self.artifacts,
            "--operator-keys", str(self.operator_keys_file),
            "validate",
            "--id", self.sid,
            "--actor", "validator1",
            "--token", token
        ]
        self.assertEqual(main(argv), 0)

        state = machine._read(self.sid)
        payload = ReviewStateMachine.payload(state, "APPROVE", "reviewer1")
        token = hmac.new(self.reviewer_key, canonical(payload), hashlib.sha256).hexdigest()

        argv = [
            "--storage", self.storage,
            "--artifacts", self.artifacts,
            "--operator-keys", str(self.operator_keys_file),
            "approve",
            "--id", self.sid,
            "--actor", "reviewer1",
            "--token", token
        ]
        self.assertEqual(main(argv), 0)

        argv = [
            "--storage", self.storage,
            "--artifacts", self.artifacts,
            "--operator-keys", str(self.operator_keys_file),
            "eligible",
            "--id", self.sid
        ]
        self.assertEqual(main(argv), 0)

if __name__ == "__main__":
    unittest.main()
