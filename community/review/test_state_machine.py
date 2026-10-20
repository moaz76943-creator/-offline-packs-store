import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from community.review.state_machine import (
    ReviewStateMachine, ReviewState, sign, sha256
)


class TestReviewStateMachine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.storage_dir = self.root / "storage"
        self.artifact_dir = self.root / "artifacts"
        self.storage_dir.mkdir()
        self.artifact_dir.mkdir()

        self.val_key = os.urandom(32)
        self.rev_key = os.urandom(32)

        self.validator_keys = {"val1": self.val_key}
        self.reviewer_keys = {"rev1": self.rev_key}

        self.machine = ReviewStateMachine(
            self.storage_dir,
            self.artifact_dir,
            validator_keys=self.validator_keys,
            reviewer_keys=self.reviewer_keys
        )

        self.valid_metadata = {
            "source_id": "test_src",
            "language": "eng",
            "sense_id": "sense1",
            "license_id": "CC0-1.0",
            "dataset_version": "1.0",
            "publisher": "test pub",
            "origin_url": "http://example.com",
            "record_locator": "rec1",
            "source_artifact_sha256": "0" * 64,
            "rights_status": "APPROVED_FOR_REDISTRIBUTION",
            "fixture_only": False
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_artifact(self, content=b"test"):
        path = self.artifact_dir / "test.txt"
        path.write_bytes(content)
        return path, sha256(path)

    def test_full_success_path(self):
        path, chash = self._create_artifact()
        sid = "sub1"

        # Submit
        res = self.machine.submit(sid, chash, self.valid_metadata, path)
        self.assertEqual(res["state"], ReviewState.SUBMITTED.value)

        # Start validation
        res = self.machine.start_validation(sid)
        self.assertEqual(res["state"], ReviewState.VALIDATING.value)

        # Complete validation
        payload = ReviewStateMachine.payload(res, "VALIDATE", "val1")
        token = sign(self.val_key, payload)
        res = self.machine.complete_validation(sid, "val1", token)
        self.assertEqual(res["state"], ReviewState.REVIEW_REQUIRED.value)

        # Approve
        payload = ReviewStateMachine.payload(res, "APPROVE", "rev1")
        token = sign(self.rev_key, payload)
        res = self.machine.review(sid, "rev1", True, token)
        self.assertEqual(res["state"], ReviewState.APPROVED.value)

        # Eligible
        res = self.machine.mark_published_eligible(sid)
        self.assertEqual(res["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

        # Verify handoff
        self.machine.verify_handoff(sid)

    def test_rejected_sources(self):
        path, chash = self._create_artifact()
        sid = "sub_rej"

        res = self.machine.submit(sid, chash, self.valid_metadata, path)
        res = self.machine.start_validation(sid)

        payload = ReviewStateMachine.payload(res, "VALIDATE", "val1")
        token = sign(self.val_key, payload)
        res = self.machine.complete_validation(sid, "val1", token)

        # Reject
        payload = ReviewStateMachine.payload(res, "REJECT", "rev1")
        token = sign(self.rev_key, payload)
        res = self.machine.review(sid, "rev1", False, token)
        self.assertEqual(res["state"], ReviewState.REJECTED.value)

        # Cannot mark published eligible
        with self.assertRaisesRegex(ValueError, "review not approved"):
            self.machine.mark_published_eligible(sid)

    def test_repeated_submissions(self):
        path, chash = self._create_artifact()
        sid = "sub_rep"

        res1 = self.machine.submit(sid, chash, self.valid_metadata, path)
        self.assertEqual(res1["revision"], 1)

        # Exact same submission
        res2 = self.machine.submit(sid, chash, self.valid_metadata, path)
        self.assertEqual(res2["revision"], 1)

        # Different metadata
        new_meta = dict(self.valid_metadata)
        new_meta["record_locator"] = "rec2"
        res3 = self.machine.submit(sid, chash, new_meta, path)
        self.assertEqual(res3["revision"], 2)
        self.assertEqual(res3["state"], ReviewState.SUBMITTED.value)

    def test_stale_approvals(self):
        path, chash = self._create_artifact()
        sid = "sub_stale"

        res = self.machine.submit(sid, chash, self.valid_metadata, path)
        res = self.machine.start_validation(sid)

        payload = ReviewStateMachine.payload(res, "VALIDATE", "val1")
        token = sign(self.val_key, payload)

        # Modify revision to simulate a new submission before complete_validation
        res_new = self.machine.submit(sid, chash, {**self.valid_metadata, "record_locator": "new"}, path)
        res_new = self.machine.start_validation(sid)

        # Try to use old token
        with self.assertRaisesRegex(PermissionError, "invalid or stale authorized decision"):
            self.machine.complete_validation(sid, "val1", token)

    def test_reviewer_state_conflicts(self):
        path, chash = self._create_artifact()
        sid = "sub_conf"

        res = self.machine.submit(sid, chash, self.valid_metadata, path)

        # Try to complete validation from SUBMITTED
        with self.assertRaisesRegex(ValueError, "invalid validation transition"):
            self.machine.complete_validation(sid, "val1", "dummy")

        res = self.machine.start_validation(sid)

        # Try to review from VALIDATING
        with self.assertRaisesRegex(ValueError, "invalid review transition"):
            self.machine.review(sid, "rev1", True, "dummy")

    def test_restart(self):
        path, chash = self._create_artifact()
        sid = "sub_res"

        res = self.machine.submit(sid, chash, self.valid_metadata, path)
        self.machine.start_validation(sid)

        # Create new machine instance
        new_machine = ReviewStateMachine(
            self.storage_dir,
            self.artifact_dir,
            validator_keys=self.validator_keys,
            reviewer_keys=self.reviewer_keys
        )

        # Continue from validation
        state = new_machine._read(sid)
        self.assertEqual(state["state"], ReviewState.VALIDATING.value)

        payload = ReviewStateMachine.payload(state, "VALIDATE", "val1")
        token = sign(self.val_key, payload)
        res = new_machine.complete_validation(sid, "val1", token)
        self.assertEqual(res["state"], ReviewState.REVIEW_REQUIRED.value)


if __name__ == '__main__':
    unittest.main()
