import unittest
import tempfile
import shutil
from pathlib import Path
import os
import hashlib
import json
import base64

from community.review.state_machine import ReviewStateMachine, ReviewState, sign

class TestReviewStateMachine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = Path(self.temp_dir) / "storage"
        self.artifacts = Path(self.temp_dir) / "artifacts"
        self.storage.mkdir()
        self.artifacts.mkdir()

        self.validator_key = os.urandom(32)
        self.reviewer_key = os.urandom(32)

        self.machine = ReviewStateMachine(
            self.storage, self.artifacts,
            validator_keys={"val1": self.validator_key},
            reviewer_keys={"rev1": self.reviewer_key}
        )

        self.valid_meta = {
            "source_id": "test_src",
            "language": "eng",
            "sense_id": "sense1",
            "license_id": "CC-BY-4.0",
            "dataset_version": "1.0",
            "publisher": "Test Pub",
            "origin_url": "http://example.com",
            "record_locator": "rec1",
            "source_artifact_sha256": hashlib.sha256(b"dummy").hexdigest(),
            "fixture_only": False,
            "rights_status": "APPROVED_FOR_REDISTRIBUTION"
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def write_artifact(self, name, content):
        path = self.artifacts / name
        path.write_bytes(content)
        return path, hashlib.sha256(content).hexdigest()

    def test_full_happy_path(self):
        content = b"artifact content"
        path, sha = self.write_artifact("art1.json", content)

        # Submit
        res = self.machine.submit("sub1", sha, self.valid_meta, path)
        self.assertEqual(res["state"], ReviewState.SUBMITTED.value)

        # Start validation
        res = self.machine.start_validation("sub1")
        self.assertEqual(res["state"], ReviewState.VALIDATING.value)

        # Complete validation
        payload = self.machine.payload(res, "VALIDATE", "val1")
        token = sign(self.validator_key, payload)
        res = self.machine.complete_validation("sub1", "val1", token)
        self.assertEqual(res["state"], ReviewState.REVIEW_REQUIRED.value)

        # Approve
        payload = self.machine.payload(res, "APPROVE", "rev1")
        token = sign(self.reviewer_key, payload)
        res = self.machine.review("sub1", "rev1", True, token)
        self.assertEqual(res["state"], ReviewState.APPROVED.value)

        # Eligible
        res = self.machine.mark_published_eligible("sub1")
        self.assertEqual(res["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

        # Handoff verify
        res = self.machine.verify_handoff("sub1")
        self.assertEqual(res["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

    def test_rejected_path(self):
        content = b"artifact content"
        path, sha = self.write_artifact("art1.json", content)

        res = self.machine.submit("sub1", sha, self.valid_meta, path)
        res = self.machine.start_validation("sub1")

        payload = self.machine.payload(res, "VALIDATE", "val1")
        token = sign(self.validator_key, payload)
        res = self.machine.complete_validation("sub1", "val1", token)

        # Reject
        payload = self.machine.payload(res, "REJECT", "rev1")
        token = sign(self.reviewer_key, payload)
        res = self.machine.review("sub1", "rev1", False, token)
        self.assertEqual(res["state"], ReviewState.REJECTED.value)

        # Cannot make eligible if rejected
        with self.assertRaises(ValueError):
            self.machine.mark_published_eligible("sub1")

    def test_invalid_submission(self):
        content = b"artifact content"
        path, sha = self.write_artifact("art1.json", content)

        invalid_meta = dict(self.valid_meta)
        invalid_meta["rights_status"] = "UNKNOWN"

        with self.assertRaises(ValueError):
            self.machine.submit("sub1", sha, invalid_meta, path)

    def test_interruption_and_restart(self):
        content = b"artifact content"
        path, sha = self.write_artifact("art1.json", content)

        res = self.machine.submit("sub1", sha, self.valid_meta, path)

        # New machine instance, same storage
        machine2 = ReviewStateMachine(
            self.storage, self.artifacts,
            validator_keys={"val1": self.validator_key},
            reviewer_keys={"rev1": self.reviewer_key}
        )

        # Submitting same content idempotently returns existing state
        res2 = machine2.submit("sub1", sha, self.valid_meta, path)
        self.assertEqual(res2["state"], ReviewState.SUBMITTED.value)
        self.assertEqual(res2["revision"], 1)

    def test_stale_approval(self):
        content = b"artifact content"
        path, sha = self.write_artifact("art1.json", content)

        res = self.machine.submit("sub1", sha, self.valid_meta, path)
        res = self.machine.start_validation("sub1")

        payload = self.machine.payload(res, "VALIDATE", "val1")
        token = sign(self.validator_key, payload)
        res = self.machine.complete_validation("sub1", "val1", token)

        # Approve
        payload = self.machine.payload(res, "APPROVE", "rev1")
        token = sign(self.reviewer_key, payload)
        res = self.machine.review("sub1", "rev1", True, token)

        # Modifying artifact invalidates content
        path.write_bytes(b"modified")

        with self.assertRaises(ValueError):
            self.machine.mark_published_eligible("sub1")

    def test_new_revision(self):
        content1 = b"artifact content 1"
        path1, sha1 = self.write_artifact("art1.json", content1)

        res1 = self.machine.submit("sub1", sha1, self.valid_meta, path1)
        self.assertEqual(res1["revision"], 1)

        content2 = b"artifact content 2"
        path2, sha2 = self.write_artifact("art2.json", content2)

        res2 = self.machine.submit("sub1", sha2, self.valid_meta, path2)
        self.assertEqual(res2["revision"], 2)
        self.assertEqual(len(res2["history"]), 2)

    def test_repeated_submissions(self):
        content = b"artifact content"
        path, sha = self.write_artifact("art1.json", content)

        res1 = self.machine.submit("sub1", sha, self.valid_meta, path)
        self.assertEqual(res1["revision"], 1)

        # Immediate resubmission with same content is idempotent
        res2 = self.machine.submit("sub1", sha, self.valid_meta, path)
        self.assertEqual(res2["revision"], 1)

    def test_reviewer_state_conflicts(self):
        content = b"artifact content"
        path, sha = self.write_artifact("art1.json", content)

        res = self.machine.submit("sub1", sha, self.valid_meta, path)
        res = self.machine.start_validation("sub1")

        payload = self.machine.payload(res, "VALIDATE", "val1")
        token = sign(self.validator_key, payload)
        res = self.machine.complete_validation("sub1", "val1", token)

        # Wrong token
        wrong_token = sign(os.urandom(32), payload)
        with self.assertRaises(PermissionError):
            self.machine.review("sub1", "rev1", True, wrong_token)

        # Wrong action in payload signed token
        payload_reject = self.machine.payload(res, "REJECT", "rev1")
        token_reject = sign(self.reviewer_key, payload_reject)

        with self.assertRaises(PermissionError):
            self.machine.review("sub1", "rev1", True, token_reject) # Passing True but token was signed for REJECT

if __name__ == '__main__':
    unittest.main()
