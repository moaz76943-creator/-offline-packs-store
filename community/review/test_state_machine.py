import unittest
import tempfile
import shutil
from pathlib import Path
import os
import json
import base64
import hashlib
import hmac

from community.review.state_machine import ReviewStateMachine, ReviewState, sign, canonical, sha256

class TestReviewStateMachine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_dir = Path(self.temp_dir) / "storage"
        self.artifacts_dir = Path(self.temp_dir) / "artifacts"
        self.storage_dir.mkdir()
        self.artifacts_dir.mkdir()

        self.validator_key = os.urandom(32)
        self.reviewer_key = os.urandom(32)

        self.machine = ReviewStateMachine(
            self.storage_dir, self.artifacts_dir,
            validator_keys={"validator1": self.validator_key},
            reviewer_keys={"reviewer1": self.reviewer_key}
        )

        self.valid_metadata = {
            "source_id": "test-source",
            "language": "eng",
            "sense_id": "test-sense",
            "license_id": "CC0-1.0",
            "dataset_version": "1.0",
            "publisher": "Test Pub",
            "origin_url": "http://test",
            "record_locator": "123",
            "source_artifact_sha256": "0"*64,
            "rights_status": "APPROVED_FOR_REDISTRIBUTION",
            "fixture_only": False
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _create_artifact(self, content=b"test artifact content"):
        artifact_path = self.artifacts_dir / "test_artifact.json"
        artifact_path.write_bytes(content)
        content_hash = hashlib.sha256(content).hexdigest()
        return artifact_path, content_hash

    def test_full_successful_flow(self):
        # 1. SUBMIT
        artifact_path, content_hash = self._create_artifact()
        outcome = self.machine.submit("sub-1", content_hash, self.valid_metadata, artifact_path)
        self.assertEqual(outcome["state"], ReviewState.SUBMITTED.value)
        self.assertEqual(outcome["revision"], 1)

        # 2. START VALIDATING
        outcome = self.machine.start_validation("sub-1")
        self.assertEqual(outcome["state"], ReviewState.VALIDATING.value)

        # 3. COMPLETE VALIDATION
        # compute token
        payload = ReviewStateMachine.payload(outcome, "VALIDATE", "validator1")
        token = sign(self.validator_key, payload)
        outcome = self.machine.complete_validation("sub-1", "validator1", token)
        self.assertEqual(outcome["state"], ReviewState.REVIEW_REQUIRED.value)

        # 4. REVIEW (APPROVE)
        payload = ReviewStateMachine.payload(outcome, "APPROVE", "reviewer1")
        token = sign(self.reviewer_key, payload)
        outcome = self.machine.review("sub-1", "reviewer1", True, token)
        self.assertEqual(outcome["state"], ReviewState.APPROVED.value)

        # 5. ELIGIBLE
        outcome = self.machine.mark_published_eligible("sub-1")
        self.assertEqual(outcome["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

        # Verify handoff
        verified = self.machine.verify_handoff("sub-1")
        self.assertEqual(verified["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

    def test_rejected_flow(self):
        artifact_path, content_hash = self._create_artifact()
        self.machine.submit("sub-2", content_hash, self.valid_metadata, artifact_path)
        self.machine.start_validation("sub-2")

        outcome = self.machine._read("sub-2")
        payload = ReviewStateMachine.payload(outcome, "VALIDATE", "validator1")
        token = sign(self.validator_key, payload)
        self.machine.complete_validation("sub-2", "validator1", token)

        outcome = self.machine._read("sub-2")
        payload = ReviewStateMachine.payload(outcome, "REJECT", "reviewer1")
        token = sign(self.reviewer_key, payload)
        outcome = self.machine.review("sub-2", "reviewer1", False, token)
        self.assertEqual(outcome["state"], ReviewState.REJECTED.value)

        # Cannot mark published eligible
        with self.assertRaises(ValueError):
            self.machine.mark_published_eligible("sub-2")

    def test_repeated_identical_submission(self):
        artifact_path, content_hash = self._create_artifact()
        outcome1 = self.machine.submit("sub-3", content_hash, self.valid_metadata, artifact_path)

        # Exact same submission should return the existing state and NOT increment revision
        outcome2 = self.machine.submit("sub-3", content_hash, self.valid_metadata, artifact_path)
        self.assertEqual(outcome1, outcome2)
        self.assertEqual(outcome2["revision"], 1)

    def test_new_revision_submission(self):
        artifact_path, content_hash = self._create_artifact()
        self.machine.submit("sub-4", content_hash, self.valid_metadata, artifact_path)

        # Submit with new artifact
        artifact_path2, content_hash2 = self._create_artifact(b"new content")
        outcome = self.machine.submit("sub-4", content_hash2, self.valid_metadata, artifact_path2)

        self.assertEqual(outcome["revision"], 2)
        self.assertEqual(outcome["state"], ReviewState.SUBMITTED.value)
        self.assertEqual(outcome["content_hash"], content_hash2)

    def test_invalid_metadata(self):
        artifact_path, content_hash = self._create_artifact()
        invalid_meta = self.valid_metadata.copy()
        invalid_meta["rights_status"] = "UNKNOWN"
        with self.assertRaises(ValueError):
            self.machine.submit("sub-5", content_hash, invalid_meta, artifact_path)

    def test_invalid_token(self):
        artifact_path, content_hash = self._create_artifact()
        self.machine.submit("sub-6", content_hash, self.valid_metadata, artifact_path)
        self.machine.start_validation("sub-6")

        with self.assertRaises(PermissionError):
            self.machine.complete_validation("sub-6", "validator1", "invalid_token")

    def test_restart_from_checkpoint(self):
        artifact_path, content_hash = self._create_artifact()
        self.machine.submit("sub-7", content_hash, self.valid_metadata, artifact_path)
        self.machine.start_validation("sub-7")

        # Create a new machine instance pointing to the same storage
        machine2 = ReviewStateMachine(
            self.storage_dir, self.artifacts_dir,
            validator_keys={"validator1": self.validator_key},
            reviewer_keys={"reviewer1": self.reviewer_key}
        )

        # Should be able to read state and continue
        outcome = machine2._read("sub-7")
        self.assertEqual(outcome["state"], ReviewState.VALIDATING.value)

        payload = ReviewStateMachine.payload(outcome, "VALIDATE", "validator1")
        token = sign(self.validator_key, payload)
        outcome2 = machine2.complete_validation("sub-7", "validator1", token)
        self.assertEqual(outcome2["state"], ReviewState.REVIEW_REQUIRED.value)

    def test_stale_approval(self):
        # A reviewer uses a token from a previous revision to try to approve a new revision
        artifact_path, content_hash = self._create_artifact()
        outcome1 = self.machine.submit("sub-8", content_hash, self.valid_metadata, artifact_path)
        self.machine.start_validation("sub-8")

        outcome_val1 = self.machine._read("sub-8")
        payload_val = ReviewStateMachine.payload(outcome_val1, "VALIDATE", "validator1")
        token_val = sign(self.validator_key, payload_val)
        outcome_revreq1 = self.machine.complete_validation("sub-8", "validator1", token_val)

        # Reviewer generates an approval token for this revision
        payload_app1 = ReviewStateMachine.payload(outcome_revreq1, "APPROVE", "reviewer1")
        token_app1 = sign(self.reviewer_key, payload_app1)

        # But wait, submitter uploads a new revision before reviewer submits!
        artifact_path2, content_hash2 = self._create_artifact(b"malicious new content")
        self.machine.submit("sub-8", content_hash2, self.valid_metadata, artifact_path2)
        self.machine.start_validation("sub-8")

        outcome_val2 = self.machine._read("sub-8")
        payload_val2 = ReviewStateMachine.payload(outcome_val2, "VALIDATE", "validator1")
        token_val2 = sign(self.validator_key, payload_val2)
        self.machine.complete_validation("sub-8", "validator1", token_val2)

        # Reviewer tries to use old token
        with self.assertRaises(PermissionError):
            self.machine.review("sub-8", "reviewer1", True, token_app1)

    def test_invalid_state_transitions(self):
        artifact_path, content_hash = self._create_artifact()
        outcome = self.machine.submit("sub-9", content_hash, self.valid_metadata, artifact_path)

        # Try to review before validation
        payload_app = ReviewStateMachine.payload(outcome, "APPROVE", "reviewer1")
        token_app = sign(self.reviewer_key, payload_app)
        with self.assertRaises(ValueError):
            self.machine.review("sub-9", "reviewer1", True, token_app)

        # Complete validation without starting it
        payload_val = ReviewStateMachine.payload(outcome, "VALIDATE", "validator1")
        token_val = sign(self.validator_key, payload_val)
        with self.assertRaises(ValueError):
            self.machine.complete_validation("sub-9", "validator1", token_val)

        # Start validation
        self.machine.start_validation("sub-9")

        # Try to mark published eligible before approval
        with self.assertRaises(ValueError):
            self.machine.mark_published_eligible("sub-9")

if __name__ == '__main__':
    unittest.main()
