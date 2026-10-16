import json
import os
import shutil
import tempfile
import unittest
import hashlib
import hmac
from pathlib import Path

from community.review.state_machine import ReviewStateMachine, ReviewState, sign, canonical

class TestReviewStateMachine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.storage_dir = Path(self.tmp_dir) / "storage"
        self.artifact_dir = Path(self.tmp_dir) / "artifacts"
        self.storage_dir.mkdir()
        self.artifact_dir.mkdir()

        self.val_key = os.urandom(32)
        self.rev_key = os.urandom(32)

        self.machine = ReviewStateMachine(
            self.storage_dir, self.artifact_dir,
            validator_keys={"val1": self.val_key},
            reviewer_keys={"rev1": self.rev_key}
        )

        # Create a valid fixture
        self.artifact_content = b"test artifact content"
        self.artifact_sha256 = hashlib.sha256(self.artifact_content).hexdigest()
        self.artifact_path = self.artifact_dir / "test_artifact.zip"
        self.artifact_path.write_bytes(self.artifact_content)

        self.valid_metadata = {
            "source_id": "src-1",
            "language": "eng",
            "sense_id": "sense-1",
            "license_id": "CC0-1.0",
            "dataset_version": "1.0",
            "publisher": "Test Pub",
            "origin_url": "https://example.com/test",
            "record_locator": "loc-1",
            "source_artifact_sha256": self.artifact_sha256,
            "fixture_only": False,
            "rights_status": "APPROVED_FOR_REDISTRIBUTION"
        }

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def test_full_successful_transition(self):
        sid = "sub-1"
        data = self.machine.submit(sid, self.artifact_sha256, self.valid_metadata, self.artifact_path)
        self.assertEqual(data["state"], ReviewState.SUBMITTED.value)
        self.assertEqual(data["revision"], 1)

        data = self.machine.start_validation(sid)
        self.assertEqual(data["state"], ReviewState.VALIDATING.value)

        token = sign(self.val_key, self.machine.payload(data, "VALIDATE", "val1"))
        data = self.machine.complete_validation(sid, "val1", token)
        self.assertEqual(data["state"], ReviewState.REVIEW_REQUIRED.value)

        token = sign(self.rev_key, self.machine.payload(data, "APPROVE", "rev1"))
        data = self.machine.review(sid, "rev1", True, token)
        self.assertEqual(data["state"], ReviewState.APPROVED.value)

        data = self.machine.mark_published_eligible(sid)
        self.assertEqual(data["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

        verified = self.machine.verify_handoff(sid)
        self.assertEqual(verified["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

    def test_rejected_source(self):
        sid = "sub-2"
        data = self.machine.submit(sid, self.artifact_sha256, self.valid_metadata, self.artifact_path)
        data = self.machine.start_validation(sid)
        token = sign(self.val_key, self.machine.payload(data, "VALIDATE", "val1"))
        data = self.machine.complete_validation(sid, "val1", token)

        token = sign(self.rev_key, self.machine.payload(data, "REJECT", "rev1"))
        data = self.machine.review(sid, "rev1", False, token)
        self.assertEqual(data["state"], ReviewState.REJECTED.value)

        with self.assertRaises(ValueError):
            self.machine.mark_published_eligible(sid)

    def test_stale_approval(self):
        sid = "sub-3"
        data = self.machine.submit(sid, self.artifact_sha256, self.valid_metadata, self.artifact_path)
        data = self.machine.start_validation(sid)
        token = sign(self.val_key, self.machine.payload(data, "VALIDATE", "val1"))
        data = self.machine.complete_validation(sid, "val1", token)

        # Use token from revision 1, but let's say someone else submitted a new revision
        old_token = sign(self.rev_key, self.machine.payload(data, "APPROVE", "rev1"))

        # Create new revision by submitting changed metadata
        new_metadata = dict(self.valid_metadata)
        new_metadata["publisher"] = "Different Pub"
        data = self.machine.submit(sid, self.artifact_sha256, new_metadata, self.artifact_path)
        self.assertEqual(data["revision"], 2)

        # New validation
        data = self.machine.start_validation(sid)
        val_token = sign(self.val_key, self.machine.payload(data, "VALIDATE", "val1"))
        data = self.machine.complete_validation(sid, "val1", val_token)

        with self.assertRaises(PermissionError):
            # Attempt to use old token
            self.machine.review(sid, "rev1", True, old_token)

    def test_repeated_submissions(self):
        sid = "sub-4"
        data1 = self.machine.submit(sid, self.artifact_sha256, self.valid_metadata, self.artifact_path)

        # Exact duplicate
        data2 = self.machine.submit(sid, self.artifact_sha256, self.valid_metadata, self.artifact_path)
        self.assertEqual(data1["revision"], data2["revision"])

        # Change metadata
        new_metadata = dict(self.valid_metadata)
        new_metadata["sense_id"] = "sense-2"
        data3 = self.machine.submit(sid, self.artifact_sha256, new_metadata, self.artifact_path)
        self.assertEqual(data3["revision"], 2)

    def test_reviewer_state_conflicts(self):
        sid = "sub-5"
        data = self.machine.submit(sid, self.artifact_sha256, self.valid_metadata, self.artifact_path)

        # Can't review before validating
        with self.assertRaises(ValueError):
            token = sign(self.rev_key, self.machine.payload(data, "APPROVE", "rev1"))
            self.machine.review(sid, "rev1", True, token)

    def test_invalid_metadata(self):
        sid = "sub-6"
        invalid_meta = dict(self.valid_metadata)
        invalid_meta["rights_status"] = "PENDING"

        with self.assertRaises(ValueError):
            self.machine.submit(sid, self.artifact_sha256, invalid_meta, self.artifact_path)

        invalid_meta2 = dict(self.valid_metadata)
        invalid_meta2["fixture_only"] = True
        with self.assertRaises(ValueError):
            self.machine.submit(sid, self.artifact_sha256, invalid_meta2, self.artifact_path)

    def test_restart_idempotency(self):
        sid = "sub-7"
        data = self.machine.submit(sid, self.artifact_sha256, self.valid_metadata, self.artifact_path)
        data = self.machine.start_validation(sid)

        # Recreate machine instance (simulate restart)
        machine2 = ReviewStateMachine(
            self.storage_dir, self.artifact_dir,
            validator_keys={"val1": self.val_key},
            reviewer_keys={"rev1": self.rev_key}
        )
        data2 = machine2._read(sid)
        self.assertEqual(data2["state"], ReviewState.VALIDATING.value)

if __name__ == "__main__":
    unittest.main()
