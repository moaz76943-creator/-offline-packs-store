import unittest
import os
import shutil
import tempfile
import json
from community.review.state_machine import ReviewStateMachine, ReviewState

class TestReviewStateMachine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.sm = ReviewStateMachine(self.test_dir)
        self.base_meta = {
            "language": "en",
            "translation_direction": "es-en",
            "lexical_sense": "test_sense"
        }

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_full_workflow_success(self):
        sub_id = "sub-1"
        hash_val = "hash-1"

        # SUBMITTED
        res = self.sm.submit(sub_id, hash_val, self.base_meta)
        self.assertEqual(res["state"], ReviewState.SUBMITTED.value)

        # VALIDATING
        res = self.sm.start_validation(sub_id)
        self.assertEqual(res["state"], ReviewState.VALIDATING.value)

        # Evidence
        self.sm.provide_evidence(sub_id, "licensing_check", {"passed": True})
        self.sm.provide_evidence(sub_id, "algorithmic_check", {"passed": True})

        # Complete validation -> REVIEW_REQUIRED
        res = self.sm.complete_validation(sub_id)
        self.assertEqual(res["state"], ReviewState.REVIEW_REQUIRED.value)

        # APPROVED
        res = self.sm.review(sub_id, "reviewer-1", True, "Looks good")
        self.assertEqual(res["state"], ReviewState.APPROVED.value)

        # PUBLISHED_ELIGIBLE
        res = self.sm.mark_published_eligible(sub_id)
        self.assertEqual(res["state"], ReviewState.PUBLISHED_ELIGIBLE.value)

        # Handoff artifact should exist
        handoff_path = os.path.join(self.sm.handoff_dir, f"{sub_id}_handoff.json")
        self.assertTrue(os.path.exists(handoff_path))
        with open(handoff_path, "r") as f:
            handoff = json.load(f)
            self.assertEqual(handoff["approved_by"], ["reviewer-1"])

    def test_missing_metadata(self):
        with self.assertRaises(ValueError) as context:
            self.sm.submit("sub-err", "hash-err", {"language": "en"})
        self.assertIn("Missing translation_direction", str(context.exception))

    def test_rejection_missing_licensing(self):
        sub_id = "sub-2"
        self.sm.submit(sub_id, "hash-2", self.base_meta)
        self.sm.start_validation(sub_id)
        res = self.sm.complete_validation(sub_id)
        self.assertEqual(res["state"], ReviewState.REJECTED.value)
        self.assertEqual(res["rejection_reason"], "Missing mandatory licensing check evidence")

    def test_rejection_failed_licensing(self):
        sub_id = "sub-3"
        self.sm.submit(sub_id, "hash-3", self.base_meta)
        self.sm.start_validation(sub_id)
        self.sm.provide_evidence(sub_id, "licensing_check", {"passed": False})
        res = self.sm.complete_validation(sub_id)
        self.assertEqual(res["state"], ReviewState.REJECTED.value)
        self.assertEqual(res["rejection_reason"], "Licensing check failed")

    def test_rejection_failed_algorithmic(self):
        sub_id = "sub-4"
        self.sm.submit(sub_id, "hash-4", self.base_meta)
        self.sm.start_validation(sub_id)
        self.sm.provide_evidence(sub_id, "licensing_check", {"passed": True})
        self.sm.provide_evidence(sub_id, "algorithmic_check", {"passed": False})
        res = self.sm.complete_validation(sub_id)
        self.assertEqual(res["state"], ReviewState.REJECTED.value)
        self.assertEqual(res["rejection_reason"], "Algorithmic check failed")

    def test_human_rejection(self):
        sub_id = "sub-5"
        self.sm.submit(sub_id, "hash-5", self.base_meta)
        self.sm.start_validation(sub_id)
        self.sm.provide_evidence(sub_id, "licensing_check", {"passed": True})
        self.sm.complete_validation(sub_id)

        res = self.sm.review(sub_id, "reviewer-1", False, "Spam content")
        self.assertEqual(res["state"], ReviewState.REJECTED.value)
        self.assertIn("Spam content", res["rejection_reason"])

    def test_duplicate_submission_idempotency(self):
        sub_id = "sub-6"
        hash_val = "hash-6"
        res1 = self.sm.submit(sub_id, hash_val, self.base_meta)

        self.sm.start_validation(sub_id)

        # Submit exactly the same hash again
        res2 = self.sm.submit(sub_id, hash_val, self.base_meta)
        self.assertEqual(res2["state"], ReviewState.VALIDATING.value) # Returns existing state

    def test_correction_submission_new_hash(self):
        sub_id = "sub-7"
        self.sm.submit(sub_id, "hash-7-old", self.base_meta)
        self.sm.start_validation(sub_id)

        # Submit with new hash -> should create a new revision but keep history
        res = self.sm.submit(sub_id, "hash-7-new", self.base_meta)
        self.assertEqual(res["state"], ReviewState.SUBMITTED.value)
        self.assertEqual(res["content_hash"], "hash-7-new")
        self.assertTrue(len(res["history"]) > 1)

    def test_reviewer_state_conflicts(self):
        sub_id = "sub-8"
        self.sm.submit(sub_id, "hash-8", self.base_meta)

        # Cannot review in SUBMITTED
        with self.assertRaises(ValueError):
            self.sm.review(sub_id, "reviewer-1", True)

        self.sm.start_validation(sub_id)

        # Cannot review in VALIDATING
        with self.assertRaises(ValueError):
            self.sm.review(sub_id, "reviewer-1", True)

    def test_restart_recovery(self):
        sub_id = "sub-9"
        self.sm.submit(sub_id, "hash-9", self.base_meta)
        self.sm.start_validation(sub_id)

        # Create a new SM instance pointing to the same dir (simulating restart)
        sm_new = ReviewStateMachine(self.test_dir)
        data = sm_new._read_checkpoint(sub_id)
        self.assertIsNotNone(data)
        self.assertEqual(data["state"], ReviewState.VALIDATING.value)

        # We can continue
        sm_new.provide_evidence(sub_id, "licensing_check", {"passed": True})
        res = sm_new.complete_validation(sub_id)
        self.assertEqual(res["state"], ReviewState.REVIEW_REQUIRED.value)

    def test_enqueue_manifest(self):
        manifest_path = os.path.join(self.test_dir, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump({
                "submissions": [
                    {"submission_id": "m-1", "content_hash": "h-1", "metadata": self.base_meta},
                    {"submission_id": "m-2", "content_hash": "h-2", "metadata": self.base_meta}
                ]
            }, f)

        res = self.sm.enqueue_manifest(manifest_path)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["submission_id"], "m-1")
        self.assertEqual(res[1]["submission_id"], "m-2")

    def test_stale_approvals(self):
        sub_id = "sub-10"
        self.sm.submit(sub_id, "hash-10", self.base_meta)
        self.sm.start_validation(sub_id)
        self.sm.provide_evidence(sub_id, "licensing_check", {"passed": True})
        self.sm.complete_validation(sub_id)
        self.sm.review(sub_id, "reviewer-1", True, "LGTM")

        # Someone updates the hash, approval should become stale
        self.sm.submit(sub_id, "hash-10-updated", self.base_meta)

        # State should be SUBMITTED
        res = self.sm._read_checkpoint(sub_id)
        self.assertEqual(res["state"], ReviewState.SUBMITTED.value)
        self.assertEqual(res["content_hash"], "hash-10-updated")
        self.assertTrue(len(res["history"]) > 2)

if __name__ == '__main__':
    unittest.main()
