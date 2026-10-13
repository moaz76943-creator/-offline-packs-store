"""Fail-closed merge policy regression tests; no real GitHub writes."""
import unittest
from unittest.mock import patch

from tools.merge_coordinator.coordinator import ApiError, GitHub, decide, evidence_for, inventory
from tools.merge_coordinator.policy import (
    checks_pass, conflicts, latest_approval, protection_is_enforced,
    risk_for, skip_message, state_for,
)

SHA = "a" * 40


def pr(number=42, draft=False, paths=None, labels=()):
    return {"number": number, "title": "sample", "html_url": f"https://github.com/x/pull/{number}",
            "draft": draft, "head": {"sha": SHA},
            "labels": [{"name": x} for x in labels]}


def good_check(name="public-pr-merge-gate"):
    return {"name": name, "head_sha": SHA, "status": "completed",
            "conclusion": "success", "app": {"slug": "github-actions"}}


def strict_protection():
    return {"required_status_checks": {"strict": True, "contexts": ["public-pr-merge-gate"]},
            "enforce_admins": {"enabled": True},
            "required_pull_request_reviews": {"required_approving_review_count": 1}}


class PolicyTests(unittest.TestCase):
    def test_drafts_cannot_merge_even_when_files_do_not_overlap(self):
        self.assertEqual(state_for(pr(draft=True), ["docs/guide.md"], [], {42})["status"], "DRAFT")

    def test_superseded_originals_never_auto_merge(self):
        self.assertEqual(state_for(pr(95), ["tools/corpus_dedupe/core.py"], [], {95, 136})["status"],
                         "SUPERSEDED_REVIEW")

    def test_competing_options_are_quarantined(self):
        self.assertEqual(state_for(pr(100), ["tools/open_export/exporter.py"], [], {100, 101})["status"],
                         "COMPETING_REVIEW")

    def test_overlap_graph_is_order_independent(self):
        result = conflicts({9: ["a", "b"], 7: ["b", "c"], 8: ["z"]})
        self.assertEqual(result, {7: [9], 9: [7]})

    def test_overlap_cannot_be_auto_merged(self):
        self.assertEqual(state_for(pr(), ["docs/readme.md"], [19], {19, 42})["status"],
                         "OVERLAPPING_REVIEW")

    def test_code_requires_explicit_approval_and_critical_requires_human(self):
        self.assertEqual(state_for(pr(), ["tools/source.py"], [], {42})["status"],
                         "OWNER_APPROVAL_REQUIRED")
        self.assertEqual(state_for(pr(labels=["merge-safe-approved"]),
                                   [".github/workflows/test.yml"], [], {42})["status"],
                         "HUMAN_REVIEW")

    def test_documents_only_can_be_candidate(self):
        self.assertEqual(risk_for(["docs/more.md"]), "DOCS")
        self.assertEqual(state_for(pr(), ["docs/more.md"], [], {42})["status"], "CANDIDATE")

    def test_skip_variants_rejected(self):
        for x in ("[skip ci]", "[ci skip]", "[no ci]", "[skip actions]", "[actions skip]",
                  "\nSkip-Checks: true\n"):
            with self.subTest(x=x):
                self.assertTrue(skip_message("fix\n" + x))
        self.assertFalse(skip_message("fix: normal PR"))

    def test_checks_require_complete_success_from_actions(self):
        self.assertTrue(checks_pass([good_check()])[0])
        self.assertFalse(checks_pass([])[0])
        self.assertFalse(checks_pass([dict(good_check(), conclusion="skipped")])[0])
        self.assertFalse(checks_pass([dict(good_check(), app={"slug": "untrusted-app"})])[0])
        self.assertFalse(checks_pass([good_check(), dict(good_check("other"), conclusion="failure")])[0])
        self.assertFalse(checks_pass([good_check()], ["special-quality"])[0])

    def test_branch_protection_requires_strict_gate_admin_and_review(self):
        branch = {"protected": True}
        self.assertTrue(protection_is_enforced(branch, strict_protection())[0])
        self.assertFalse(protection_is_enforced({"protected": False}, strict_protection())[0])
        x = strict_protection()
        x["required_status_checks"]["strict"] = False
        self.assertFalse(protection_is_enforced(branch, x)[0])
        x = strict_protection()
        x["enforce_admins"]["enabled"] = False
        self.assertFalse(protection_is_enforced(branch, x)[0])

    def test_current_head_review_only(self):
        reviews = [{"user": {"login": "reviewer"}, "state": "APPROVED", "commit_id": SHA,
                    "submitted_at": "2026-10-13T10:00:00Z"}]
        self.assertTrue(latest_approval(reviews, SHA))
        self.assertFalse(latest_approval(reviews, "b" * 40))
        reviews.append({"user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED",
                        "commit_id": SHA, "submitted_at": "2026-10-13T10:01:00Z"})
        self.assertFalse(latest_approval(reviews, SHA))


class ApiContractTests(unittest.TestCase):
    def test_check_run_pagination_accepts_github_envelope(self):
        api = GitHub("fake")
        with patch.object(api, "get", return_value={"total_count": 1, "check_runs": [good_check()]}):
            self.assertEqual(len(api.pages("/commits/" + SHA + "/check-runs")), 1)

    def test_an_unprotected_branch_never_merges(self):
        class Fake:
            def get(self, route):
                if route == "/branches/main":
                    return {"protected": False, "commit": {"sha": SHA}}
                raise AssertionError("Unexpected API call")
        report = {"main_sha": SHA, "prs": [
            state_for(pr(), ["docs/guide.md"], [], {42})]}
        result = decide(Fake(), report, True, 3)
        self.assertEqual(result["prs"][0]["status"], "BLOCKED_PROTECTION")
        self.assertEqual(result["merge_events"], [])

    def test_exact_tip_change_blocks_merge_before_checks(self):
        class Fake:
            def get(self, route):
                if route == "/pulls/42":
                    return {"draft": False, "state": "open", "head": {"sha": "b" * 40},
                            "base": {"ref": "main", "sha": SHA}}
                raise AssertionError("Unexpected network call")
        status, _ = evidence_for(Fake(), state_for(pr(), ["docs/guide.md"], [], {42}),
                                 ["public-pr-merge-gate"], SHA)
        self.assertEqual(status, "STALE_PR")

    def test_incomplete_file_inventory_fails_closed(self):
        class Fake:
            def get(self, route):
                if route == "/branches/main":
                    return {"protected": False, "commit": {"sha": SHA}}
                raise AssertionError(route)
            def pages(self, route):
                if route.startswith("/pulls?"):
                    return [pr()]
                if route.endswith("/files"):
                    raise ApiError(403, "rate limit")
                raise AssertionError(route)
        result = inventory(Fake())
        self.assertFalse(result["file_inventory_complete"])
        self.assertEqual(result["prs"][0]["status"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
