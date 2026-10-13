"""Regression contract: no unattended merge unless main is independently protected."""
import unittest
import coordinator


def safe_policy():
    return {
        "required_status_checks": {
            "strict": True,
            "contexts": ["public-pr-merge-gate"],
        },
        "required_pull_request_reviews": {"required_approving_review_count": 1},
        "enforce_admins": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    }


class MainProtectionTests(unittest.TestCase):
    def inspect(self, branch=None, policy=None):
        checker = getattr(coordinator, "protection_error", None)
        self.assertTrue(callable(checker), "main protection gate is missing")
        return checker({"protected": True} if branch is None else branch, safe_policy() if policy is None else policy)

    def test_independently_verified_strict_protection_is_accepted(self):
        self.assertIsNone(self.inspect())

    def test_unprotected_main_is_blocked(self):
        self.assertIsNotNone(self.inspect(branch={"protected": False}))

    def test_unknown_protection_is_blocked(self):
        self.assertIsNotNone(self.inspect(policy={}))

    def test_unverified_required_check_is_blocked(self):
        x = safe_policy()
        x["required_status_checks"]["contexts"] = ["validate"]
        self.assertIsNotNone(self.inspect(policy=x))

    def test_non_strict_ci_is_blocked(self):
        x = safe_policy()
        x["required_status_checks"]["strict"] = False
        self.assertIsNotNone(self.inspect(policy=x))

    def test_missing_human_review_is_blocked(self):
        x = safe_policy()
        x["required_pull_request_reviews"]["required_approving_review_count"] = 0
        self.assertIsNotNone(self.inspect(policy=x))

    def test_administrator_bypass_is_blocked(self):
        x = safe_policy()
        x["enforce_admins"]["enabled"] = False
        self.assertIsNotNone(self.inspect(policy=x))

    def test_force_pushes_and_branch_deletion_are_blocked(self):
        for key in ("allow_force_pushes", "allow_deletions"):
            with self.subTest(key=key):
                x = safe_policy()
                x[key] = {"enabled": True}
                self.assertIsNotNone(self.inspect(policy=x))

    def test_incomplete_protection_response_is_blocked(self):
        x = safe_policy()
        del x["allow_force_pushes"]
        self.assertIsNotNone(self.inspect(policy=x))


if __name__ == "__main__":
    unittest.main()
