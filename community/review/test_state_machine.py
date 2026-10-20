import hashlib
import hmac
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from community.review.state_machine import ReviewStateMachine, ReviewState, canonical


class TestReviewStateMachine(unittest.TestCase):

    def setUp(self):
        self.storage = tempfile.mkdtemp(prefix="test_storage_")
        self.artifacts = tempfile.mkdtemp(prefix="test_artifacts_")

        self.validator_key = os.urandom(32)
        self.reviewer_key = os.urandom(32)

        self.machine = ReviewStateMachine(
            self.storage,
            self.artifacts,
            validator_keys={"validator1": self.validator_key},
            reviewer_keys={"reviewer1": self.reviewer_key}
        )

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

    def tearDown(self):
        shutil.rmtree(self.storage)
        shutil.rmtree(self.artifacts)

    def test_submit(self):
        outcome = self.machine.submit(self.sid, self.content_hash, self.metadata, self.artifact_path)
        self.assertEqual(outcome["state"], ReviewState.SUBMITTED.value)
        self.assertEqual(outcome["revision"], 1)

    def test_duplicate_submit(self):
        self.machine.submit(self.sid, self.content_hash, self.metadata, self.artifact_path)
        outcome2 = self.machine.submit(self.sid, self.content_hash, self.metadata, self.artifact_path)
        self.assertEqual(outcome2["revision"], 1)
        self.assertEqual(len(outcome2["history"]), 1)

    def test_new_revision(self):
        self.machine.submit(self.sid, self.content_hash, self.metadata, self.artifact_path)

        new_content = b"new content"
        new_content_hash = hashlib.sha256(new_content).hexdigest()
        new_artifact_path = Path(self.artifacts) / "test_artifact2.pack"
        with open(new_artifact_path, "wb") as f:
            f.write(new_content)

        outcome2 = self.machine.submit(self.sid, new_content_hash, self.metadata, new_artifact_path)
        self.assertEqual(outcome2["revision"], 2)
        self.assertEqual(outcome2["state"], ReviewState.SUBMITTED.value)
        self.assertEqual(len(outcome2["history"]), 2)

    def _sign_payload(self, outcome, action, actor, key):
        payload = ReviewStateMachine.payload(outcome, action, actor)
        return hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()

    def test_full_flow(self):
        outcome = self.machine.submit(self.sid, self.content_hash, self.metadata, self.artifact_path)

        outcome = self.machine.start_validation(self.sid)
        self.assertEqual(outcome["state"], ReviewState.VALIDATING.value)

        token = self._sign_payload(outcome, "VALIDATE", "validator1", self.validator_key)
        outcome = self.machine.complete_validation(self.sid, "validator1", token)
        self.assertEqual(outcome["state"], ReviewState.REVIEW_REQUIRED.value)

        token = self._sign_payload(outcome, "APPROVE", "reviewer1", self.reviewer_key)
        outcome = self.machine.review(self.sid, "reviewer1", True, token)
        self.assertEqual(outcome["state"], ReviewState.APPROVED.value)

        outcome = self.machine.mark_published_eligible(self.sid)
        self.assertEqual(outcome["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

        verified = self.machine.verify_handoff(self.sid)
        self.assertEqual(verified["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

    def test_rejected_flow(self):
        outcome = self.machine.submit(self.sid, self.content_hash, self.metadata, self.artifact_path)
        outcome = self.machine.start_validation(self.sid)

        token = self._sign_payload(outcome, "VALIDATE", "validator1", self.validator_key)
        outcome = self.machine.complete_validation(self.sid, "validator1", token)

        token = self._sign_payload(outcome, "REJECT", "reviewer1", self.reviewer_key)
        outcome = self.machine.review(self.sid, "reviewer1", False, token)
        self.assertEqual(outcome["state"], ReviewState.REJECTED.value)

    def test_invalid_transitions(self):
        self.machine.submit(self.sid, self.content_hash, self.metadata, self.artifact_path)

        with self.assertRaises(ValueError):
            self.machine.complete_validation(self.sid, "validator1", "bad_token")

        with self.assertRaises(ValueError):
            self.machine.review(self.sid, "reviewer1", True, "bad_token")

        with self.assertRaises(ValueError):
            self.machine.mark_published_eligible(self.sid)

    def test_invalid_hmac(self):
        outcome = self.machine.submit(self.sid, self.content_hash, self.metadata, self.artifact_path)
        outcome = self.machine.start_validation(self.sid)

        with self.assertRaises(PermissionError):
            self.machine.complete_validation(self.sid, "validator1", "invalid_token")

    def test_missing_metadata(self):
        bad_meta = self.metadata.copy()
        del bad_meta["language"]
        with self.assertRaises(ValueError):
            self.machine.submit(self.sid, self.content_hash, bad_meta, self.artifact_path)

    def test_restart_recovery(self):
        outcome = self.machine.submit(self.sid, self.content_hash, self.metadata, self.artifact_path)
        self.machine.start_validation(self.sid)

        new_machine = ReviewStateMachine(
            self.storage,
            self.artifacts,
            validator_keys={"validator1": self.validator_key},
            reviewer_keys={"reviewer1": self.reviewer_key}
        )

        state = new_machine._read(self.sid)
        self.assertEqual(state["state"], ReviewState.VALIDATING.value)

if __name__ == "__main__":
    unittest.main()
